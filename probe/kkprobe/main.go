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
	"time"
)

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

func main() {
	configPath := "config.json"
	if len(os.Args) > 1 {
		configPath = os.Args[1]
	}

	cfg, err := loadConfig(configPath)
	if err != nil {
		fmt.Printf("load config failed: %v\n", err)
		os.Exit(1)
	}

	secret, err := base64.URLEncoding.DecodeString(cfg.Secret)
	if err != nil {
		fmt.Printf("decode secret failed: %v\n", err)
		os.Exit(1)
	}
	if len(secret) != 32 {
		fmt.Printf("secret must decode to 32 bytes, got %d\n", len(secret))
		os.Exit(1)
	}

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
				fmt.Println("heartbeat reachable again, leaving standby mode")
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
					fmt.Printf("heartbeat failed %d times, entering standby mode\n", consecutiveFailures)
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
		fmt.Printf(
			"heartbeat ok=%v latency=%s failures=%d mode=%s next=%s\n",
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
		fmt.Printf("build heartbeat failed: %v\n", err)
		return Result{OK: false}
	}

	request, err := http.NewRequest(http.MethodPost, cfg.APIURL, bytes.NewReader(body))
	if err != nil {
		fmt.Printf("build request failed: %v\n", err)
		return Result{OK: false}
	}
	request.Header.Set("Content-Type", "application/json")

	response, err := client.Do(request)
	latency := time.Since(start)
	if err != nil {
		fmt.Printf("request failed: %v\n", err)
		return Result{OK: false, Latency: latency}
	}
	defer response.Body.Close()

	responseBody, err := io.ReadAll(response.Body)
	if err != nil {
		fmt.Printf("read response failed: %v\n", err)
		return Result{OK: false, Latency: latency}
	}

	var parsed ServerResponse
	if err := json.Unmarshal(responseBody, &parsed); err != nil {
		fmt.Printf("decode response failed: %v\n", err)
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
