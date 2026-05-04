package main

import (
	"bytes"
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"encoding/xml"
	"errors"
	"fmt"
	"io"
	"math"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"
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

var logFile *os.File

func main() {
	command, configPath := parseArgs(os.Args[1:])

	if command == "uninstall" {
		if err := setupLogger(30); err != nil {
			fmt.Printf("setup logger failed: %v\n", err)
		}
		defer closeLogger()

		if err := uninstallStartup(); err != nil {
			logf("uninstall failed: %v", err)
			os.Exit(1)
		}
		logf("startup uninstalled")
		return
	}

	cfg, err := loadConfig(configPath)
	if err != nil {
		fmt.Printf("load config failed: %v\n", err)
		os.Exit(1)
	}
	if err := setupLogger(cfg.LogRetentionDays); err != nil {
		fmt.Printf("setup logger failed: %v\n", err)
		os.Exit(1)
	}
	defer closeLogger()

	if command == "install" {
		if err := installStartup(configPath); err != nil {
			logf("install failed: %v", err)
			os.Exit(1)
		}
		logf("startup installed with config=%s", configPath)
		return
	}

	if err := runProbe(cfg); err != nil {
		logf("probe stopped: %v", err)
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
	case "run", "install", "uninstall":
		command = args[0]
		if len(args) > 1 {
			configPath = args[1]
		}
	default:
		configPath = args[0]
	}

	return command, configPath
}

func runProbe(cfg Config) error {
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
		time.Sleep(interval)
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

func installStartup(configPath string) error {
	exePath, err := os.Executable()
	if err != nil {
		return err
	}
	exePath, err = filepath.Abs(exePath)
	if err != nil {
		return err
	}
	configPath, err = filepath.Abs(configPath)
	if err != nil {
		return err
	}

	switch runtime.GOOS {
	case "windows":
		return installWindowsStartup(exePath, configPath)
	case "linux":
		return installLinuxStartup(exePath, configPath)
	case "darwin":
		return installDarwinStartup(exePath, configPath)
	default:
		return fmt.Errorf("unsupported OS: %s", runtime.GOOS)
	}
}

func uninstallStartup() error {
	switch runtime.GOOS {
	case "windows":
		return uninstallWindowsStartup()
	case "linux":
		return uninstallLinuxStartup()
	case "darwin":
		return uninstallDarwinStartup()
	default:
		return fmt.Errorf("unsupported OS: %s", runtime.GOOS)
	}
}

func installWindowsStartup(exePath, configPath string) error {
	command := fmt.Sprintf("%s %s", strconv.Quote(exePath), strconv.Quote(configPath))
	if err := runCommand("reg", "add", `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, "/v", serviceName, "/t", "REG_SZ", "/d", command, "/f"); err != nil {
		return err
	}

	return startProbeProcess(exePath, configPath)
}

func uninstallWindowsStartup() error {
	return runCommand("reg", "delete", `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, "/v", serviceName, "/f")
}

func installLinuxStartup(exePath, configPath string) error {
	serviceDir, err := userConfigPath("systemd", "user")
	if err != nil {
		return err
	}
	if err := os.MkdirAll(serviceDir, 0755); err != nil {
		return err
	}

	servicePath := filepath.Join(serviceDir, "kkprobe.service")
	content := fmt.Sprintf(`[Unit]
Description=KKProbe heartbeat probe
After=network-online.target

[Service]
Type=simple
ExecStart=%s %s
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
`, strconv.Quote(exePath), strconv.Quote(configPath))

	if err := os.WriteFile(servicePath, []byte(content), 0644); err != nil {
		return err
	}
	if err := runCommand("systemctl", "--user", "daemon-reload"); err != nil {
		return err
	}
	return runCommand("systemctl", "--user", "enable", "--now", "kkprobe.service")
}

func uninstallLinuxStartup() error {
	_ = runCommand("systemctl", "--user", "disable", "--now", "kkprobe.service")
	serviceDir, err := userConfigPath("systemd", "user")
	if err != nil {
		return err
	}
	_ = os.Remove(filepath.Join(serviceDir, "kkprobe.service"))
	return runCommand("systemctl", "--user", "daemon-reload")
}

func installDarwinStartup(exePath, configPath string) error {
	agentDir, err := userHomePath("Library", "LaunchAgents")
	if err != nil {
		return err
	}
	if err := os.MkdirAll(agentDir, 0755); err != nil {
		return err
	}

	plistPath := filepath.Join(agentDir, "com.white0456.kkprobe.plist")
	content := fmt.Sprintf(`<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.white0456.kkprobe</string>
  <key>ProgramArguments</key>
  <array>
    <string>%s</string>
    <string>%s</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
</dict>
</plist>
`, xmlEscape(exePath), xmlEscape(configPath))

	if err := os.WriteFile(plistPath, []byte(content), 0644); err != nil {
		return err
	}

	target := fmt.Sprintf("gui/%d", os.Getuid())
	_ = runCommand("launchctl", "bootout", target, plistPath)
	return runCommand("launchctl", "bootstrap", target, plistPath)
}

func uninstallDarwinStartup() error {
	plistPath, err := userHomePath("Library", "LaunchAgents", "com.white0456.kkprobe.plist")
	if err != nil {
		return err
	}
	target := fmt.Sprintf("gui/%d", os.Getuid())
	_ = runCommand("launchctl", "bootout", target, plistPath)
	return os.Remove(plistPath)
}

func runCommand(name string, args ...string) error {
	logf("running command: %s %s", name, strings.Join(args, " "))
	output, err := exec.Command(name, args...).CombinedOutput()
	if len(output) > 0 {
		logf("command output: %s", strings.TrimSpace(string(output)))
	}
	return err
}

func startProbeProcess(exePath, configPath string) error {
	logf("starting probe process: %s %s", exePath, configPath)
	command := exec.Command(exePath, configPath)
	if err := command.Start(); err != nil {
		return err
	}
	logf("probe process started pid=%d", command.Process.Pid)
	return nil
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

func userConfigPath(parts ...string) (string, error) {
	configDir, err := os.UserConfigDir()
	if err != nil {
		return "", err
	}
	items := append([]string{configDir}, parts...)
	return filepath.Join(items...), nil
}

func userHomePath(parts ...string) (string, error) {
	homeDir, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	items := append([]string{homeDir}, parts...)
	return filepath.Join(items...), nil
}

func xmlEscape(value string) string {
	var builder strings.Builder
	_ = xml.EscapeText(&builder, []byte(value))
	return builder.String()
}
