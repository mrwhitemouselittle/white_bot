package main

import (
	"bytes"
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/kardianos/service"
)

const serviceName = "KKProbe"

type Config struct {
	APIURL                string  `json:"api_url"`
	KeyID                 string  `json:"key_id"`
	Secret                string  `json:"secret"`
	Device                string  `json:"device"`
	AdaptiveBackoff       bool    `json:"adaptive_backoff"`
	StandbyAfterFailures  int     `json:"standby_after_failures"`
	StandbyMinSeconds     int     `json:"standby_min_seconds"`
	StandbyMaxSeconds     int     `json:"standby_max_seconds"`
	StandbyBackoffFactor  float64 `json:"standby_backoff_factor"`
	MinIntervalSeconds    int     `json:"min_interval_seconds"`
	MaxIntervalSeconds    int     `json:"max_interval_seconds"`
	SteadyIntervalSeconds int     `json:"steady_interval_seconds"`
	RequestTimeoutSeconds int     `json:"request_timeout_seconds"`
	LogRetentionDays      int     `json:"log_retention_days"`
}

type PlainHeartbeat struct {
	Device    string `json:"device"`
	Timestamp int64  `json:"timestamp"`
}

type EncryptedHeartbeat struct {
	KeyID string `json:"key_id"`
	Nonce string `json:"nonce"`
	Data  string `json:"data"`
}

type ServerResponse struct {
	OK        int   `json:"ok"`
	Timestamp int64 `json:"timestamp"`
}

type Result struct {
	OK      bool
	Latency time.Duration
}

type probeProgram struct {
	cfg  Config
	done chan struct{}
}

var logFile *os.File

func main() {
	command, configPath := parseArgs(os.Args[1:])

	cfg := Config{}
	logRetentionDays := 30
	if commandNeedsConfig(command) {
		loadedConfig, err := loadConfig(configPath)
		if err != nil {
			fmt.Printf("load config failed: %v\n", err)
			os.Exit(1)
		}
		cfg = loadedConfig
		logRetentionDays = cfg.LogRetentionDays
	}

	if err := setupLogger(logRetentionDays); err != nil {
		fmt.Printf("setup logger failed: %v\n", err)
		os.Exit(1)
	}
	defer closeLogger()

	prg := &probeProgram{cfg: cfg}
	svc, err := newService(prg, configPath)
	if err != nil {
		logf("create service failed: %v", err)
		os.Exit(1)
	}

	if err := handleCommand(svc, command, configPath); err != nil {
		logf("command failed command=%s error=%v", command, err)
		os.Exit(1)
	}
}

func parseArgs(args []string) (string, string) {
	command := "run"
	configPath := "config.json"

	if len(args) == 0 {
		return command, configPath
	}

	switch args[0] {
	case "run", "install", "uninstall", "start", "stop", "restart", "status":
		command = args[0]
		if len(args) > 1 {
			configPath = args[1]
		}
	default:
		configPath = args[0]
	}

	return command, configPath
}

func commandNeedsConfig(command string) bool {
	return command == "run" || command == "install"
}

func newService(prg *probeProgram, configPath string) (service.Service, error) {
	absoluteConfigPath, err := filepath.Abs(configPath)
	if err != nil {
		return nil, err
	}

	svcConfig := &service.Config{
		Name:        serviceName,
		DisplayName: "KKProbe",
		Description: "KKProbe heartbeat probe for Telegram online status.",
		Arguments:   []string{absoluteConfigPath},
		Option: service.KeyValue{
			"UserService": true,
			"RunAtLoad":   true,
			"KeepAlive":   true,
			"Restart":     "always",
		},
	}
	return service.New(prg, svcConfig)
}

func handleCommand(svc service.Service, command string, configPath string) error {
	switch command {
	case "run":
		logf("running probe through service runner platform=%s interactive=%v", svc.Platform(), service.Interactive())
		return svc.Run()
	case "install":
		if err := svc.Install(); err != nil {
			return err
		}
		logf("startup installed with config=%s", configPath)
		if err := svc.Start(); err != nil {
			return err
		}
		logf("service started")
		return nil
	case "uninstall":
		if err := svc.Stop(); err != nil {
			logf("stop before uninstall ignored: %v", err)
		}
		if err := svc.Uninstall(); err != nil {
			return err
		}
		logf("service uninstalled")
		return nil
	case "start":
		if err := svc.Start(); err != nil {
			return err
		}
		logf("service started")
		return nil
	case "stop":
		if err := svc.Stop(); err != nil {
			return err
		}
		logf("service stopped")
		return nil
	case "restart":
		if err := svc.Restart(); err != nil {
			return err
		}
		logf("service restarted")
		return nil
	case "status":
		status, err := svc.Status()
		if err != nil {
			return err
		}
		logf("service status=%s", formatServiceStatus(status))
		return nil
	default:
		return fmt.Errorf("unknown command: %s", command)
	}
}

func (p *probeProgram) Start(s service.Service) error {
	p.done = make(chan struct{})
	go func() {
		if err := runProbe(p.cfg, p.done); err != nil {
			logf("probe stopped: %v", err)
		}
	}()
	return nil
}

func (p *probeProgram) Stop(s service.Service) error {
	if p.done != nil {
		close(p.done)
	}
	return nil
}

func runProbe(cfg Config, done <-chan struct{}) error {
	secret, err := base64.URLEncoding.DecodeString(cfg.Secret)
	if err != nil {
		return fmt.Errorf("decode secret failed: %w", err)
	}
	if len(secret) != 32 {
		return fmt.Errorf("secret must decode to 32 bytes, got %d", len(secret))
	}

	logf("kkprobe started device=%s api_url=%s", cfg.Device, cfg.APIURL)

	client := &http.Client{Timeout: time.Duration(cfg.RequestTimeoutSeconds) * time.Second}
	interval := time.Duration(cfg.MinIntervalSeconds) * time.Second
	results := make([]Result, 0, 10)
	consecutiveFailures := 0
	standbyMode := false
	standbyInterval := time.Duration(cfg.StandbyMinSeconds) * time.Second

	for {
		select {
		case <-done:
			logf("stop signal received")
			return nil
		default:
		}

		result := sendHeartbeat(client, cfg, secret)

		if result.OK {
			if standbyMode {
				logf("heartbeat reachable again, leaving standby mode")
			}
			standbyMode = false
			standbyInterval = time.Duration(cfg.StandbyMinSeconds) * time.Second
			consecutiveFailures = 0
			results = appendResult(results, result)

			if cfg.AdaptiveBackoff {
				interval = nextAdaptiveInterval(interval, cfg, results)
			} else {
				interval = time.Duration(cfg.SteadyIntervalSeconds) * time.Second
			}
		} else {
			consecutiveFailures++
			results = appendResult(results, result)

			if consecutiveFailures >= cfg.StandbyAfterFailures {
				if !standbyMode {
					logf("heartbeat failed %d times, entering standby mode", consecutiveFailures)
					standbyInterval = time.Duration(cfg.StandbyMinSeconds) * time.Second
				}
				standbyMode = true
				interval = standbyInterval
				standbyInterval = nextStandbyInterval(standbyInterval, cfg)
			} else if cfg.AdaptiveBackoff {
				interval = nextAdaptiveInterval(interval, cfg, results)
			} else {
				interval = time.Duration(cfg.SteadyIntervalSeconds) * time.Second
			}
		}

		mode := "normal"
		if standbyMode {
			mode = "standby"
		}
		logf(
			"heartbeat ok=%v latency=%s failures=%d mode=%s next=%s",
			result.OK,
			result.Latency,
			consecutiveFailures,
			mode,
			interval,
		)
		if !sleepOrDone(interval, done) {
			logf("stop signal received")
			return nil
		}
	}
}

func loadConfig(path string) (Config, error) {
	file, err := os.Open(path)
	if err != nil {
		return Config{}, err
	}
	defer file.Close()

	var cfg Config
	if err := json.NewDecoder(file).Decode(&cfg); err != nil {
		return Config{}, err
	}

	if cfg.APIURL == "" {
		return Config{}, errors.New("api_url is required")
	}
	if cfg.KeyID == "" {
		return Config{}, errors.New("key_id is required")
	}
	if cfg.Secret == "" {
		return Config{}, errors.New("secret is required")
	}
	if cfg.Device == "" {
		return Config{}, errors.New("device is required")
	}
	if cfg.MinIntervalSeconds <= 0 {
		cfg.MinIntervalSeconds = 5
	}
	if cfg.MaxIntervalSeconds <= 0 {
		cfg.MaxIntervalSeconds = 60
	}
	if cfg.StandbyAfterFailures <= 0 {
		cfg.StandbyAfterFailures = 5
	}
	if cfg.StandbyMinSeconds <= 0 {
		cfg.StandbyMinSeconds = 10
	}
	if cfg.StandbyMaxSeconds <= 0 {
		cfg.StandbyMaxSeconds = 300
	}
	if cfg.StandbyBackoffFactor <= 1 {
		cfg.StandbyBackoffFactor = 1.8
	}
	if cfg.SteadyIntervalSeconds <= 0 {
		cfg.SteadyIntervalSeconds = 30
	}
	if cfg.RequestTimeoutSeconds <= 0 {
		cfg.RequestTimeoutSeconds = 10
	}
	if cfg.LogRetentionDays <= 0 {
		cfg.LogRetentionDays = 30
	}

	return cfg, nil
}

func appendResult(results []Result, result Result) []Result {
	results = append(results, result)
	if len(results) > 10 {
		return results[1:]
	}
	return results
}

func sendHeartbeat(client *http.Client, cfg Config, secret []byte) Result {
	start := time.Now()
	body, err := buildHeartbeat(cfg, secret)
	if err != nil {
		logf("build heartbeat failed: %v", err)
		return Result{OK: false}
	}

	request, err := http.NewRequest(http.MethodPost, cfg.APIURL, bytes.NewReader(body))
	if err != nil {
		logf("build request failed: %v", err)
		return Result{OK: false}
	}
	request.Header.Set("Content-Type", "application/json")

	response, err := client.Do(request)
	latency := time.Since(start)
	if err != nil {
		logf("request failed: %v", err)
		return Result{OK: false, Latency: latency}
	}
	defer response.Body.Close()

	responseBody, err := io.ReadAll(response.Body)
	if err != nil {
		logf("read response failed: %v", err)
		return Result{OK: false, Latency: latency}
	}

	var parsed ServerResponse
	if err := json.Unmarshal(responseBody, &parsed); err != nil {
		logf("decode response failed: %v", err)
		return Result{OK: false, Latency: latency}
	}

	return Result{OK: response.StatusCode == http.StatusOK && parsed.OK == 1, Latency: latency}
}

func buildHeartbeat(cfg Config, secret []byte) ([]byte, error) {
	block, err := aes.NewCipher(secret)
	if err != nil {
		return nil, err
	}

	aesgcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, err
	}

	nonce := make([]byte, aesgcm.NonceSize())
	if _, err := rand.Read(nonce); err != nil {
		return nil, err
	}

	plain := PlainHeartbeat{
		Device:    cfg.Device,
		Timestamp: time.Now().Unix(),
	}
	plainJSON, err := json.Marshal(plain)
	if err != nil {
		return nil, err
	}

	ciphertext := aesgcm.Seal(nil, nonce, plainJSON, []byte(cfg.KeyID))
	encrypted := EncryptedHeartbeat{
		KeyID: cfg.KeyID,
		Nonce: base64.URLEncoding.EncodeToString(nonce),
		Data:  base64.URLEncoding.EncodeToString(ciphertext),
	}
	return json.Marshal(encrypted)
}

func nextAdaptiveInterval(current time.Duration, cfg Config, results []Result) time.Duration {
	minInterval := time.Duration(cfg.MinIntervalSeconds) * time.Second
	maxInterval := time.Duration(cfg.MaxIntervalSeconds) * time.Second

	if len(results) < 4 {
		return minInterval
	}

	lossRate := calculateLossRate(results)
	stability := calculateLatencyStability(results)

	if lossRate == 0 && stability <= 0.25 {
		next := time.Duration(float64(current) * 1.4)
		return clampDuration(next, minInterval, maxInterval)
	}

	if lossRate <= 0.1 && stability <= 0.5 {
		next := time.Duration(float64(current) * 1.15)
		return clampDuration(next, minInterval, maxInterval)
	}

	next := time.Duration(float64(current) * 0.5)
	return clampDuration(next, minInterval, maxInterval)
}

func nextStandbyInterval(current time.Duration, cfg Config) time.Duration {
	minInterval := time.Duration(cfg.StandbyMinSeconds) * time.Second
	maxInterval := time.Duration(cfg.StandbyMaxSeconds) * time.Second
	next := time.Duration(float64(current) * cfg.StandbyBackoffFactor)
	return clampDuration(next, minInterval, maxInterval)
}

func calculateLossRate(results []Result) float64 {
	lost := 0
	for _, result := range results {
		if !result.OK {
			lost++
		}
	}
	return float64(lost) / float64(len(results))
}

func calculateLatencyStability(results []Result) float64 {
	latencies := make([]float64, 0, len(results))
	for _, result := range results {
		if result.OK && result.Latency > 0 {
			latencies = append(latencies, float64(result.Latency.Milliseconds()))
		}
	}
	if len(latencies) < 2 {
		return 1
	}

	var sum float64
	for _, latency := range latencies {
		sum += latency
	}
	avg := sum / float64(len(latencies))
	if avg == 0 {
		return 1
	}

	var variance float64
	for _, latency := range latencies {
		diff := latency - avg
		variance += diff * diff
	}
	stddev := math.Sqrt(variance / float64(len(latencies)))
	return stddev / avg
}

func clampDuration(value, minValue, maxValue time.Duration) time.Duration {
	if value < minValue {
		return minValue
	}
	if value > maxValue {
		return maxValue
	}
	return value
}

func sleepOrDone(duration time.Duration, done <-chan struct{}) bool {
	timer := time.NewTimer(duration)
	defer timer.Stop()

	select {
	case <-timer.C:
		return true
	case <-done:
		return false
	}
}

func formatServiceStatus(status service.Status) string {
	switch status {
	case service.StatusRunning:
		return "running"
	case service.StatusStopped:
		return "stopped"
	default:
		return "unknown"
	}
}

func setupLogger(retentionDays int) error {
	exeDir, err := executableDir()
	if err != nil {
		return err
	}

	logDir := filepath.Join(exeDir, "logs")
	if err := os.MkdirAll(logDir, 0755); err != nil {
		return err
	}
	cleanupLogs(logDir, retentionDays)

	logPath := filepath.Join(logDir, fmt.Sprintf("kkprobe-%s.log", time.Now().Format("2006-01-02")))
	file, err := os.OpenFile(logPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0644)
	if err != nil {
		return err
	}
	logFile = file
	return nil
}

func closeLogger() {
	if logFile != nil {
		_ = logFile.Close()
	}
}

func logf(format string, args ...any) {
	line := fmt.Sprintf("[%s] %s\n", time.Now().Format("2006-01-02 15:04:05"), fmt.Sprintf(format, args...))
	fmt.Print(line)
	if logFile != nil {
		_, _ = logFile.WriteString(line)
	}
}

func cleanupLogs(logDir string, retentionDays int) {
	if retentionDays <= 0 {
		retentionDays = 30
	}
	entries, err := os.ReadDir(logDir)
	if err != nil {
		return
	}

	cutoff := time.Now().AddDate(0, 0, -retentionDays)
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasPrefix(entry.Name(), "kkprobe-") || !strings.HasSuffix(entry.Name(), ".log") {
			continue
		}

		info, err := entry.Info()
		if err == nil && info.ModTime().Before(cutoff) {
			_ = os.Remove(filepath.Join(logDir, entry.Name()))
		}
	}
}

func executableDir() (string, error) {
	exePath, err := os.Executable()
	if err != nil {
		return "", err
	}
	exePath, err = filepath.Abs(exePath)
	if err != nil {
		return "", err
	}
	return filepath.Dir(exePath), nil
}
