package config

import (
	"os"
	"time"

	"gopkg.in/yaml.v3"
)

type Config struct {
	Database    DatabaseConfig    `yaml:"database"`
	Scheduler   SchedulerConfig   `yaml:"scheduler"`
	Telegram    TelegramConfig    `yaml:"telegram"`
	Dashboard   DashboardConfig   `yaml:"dashboard"`
	PythonParser PythonParserConfig `yaml:"python_parser"`
}

type PythonParserConfig struct {
	Enabled    bool   `yaml:"enabled"`
	ScriptPath string `yaml:"script_path"`
}

type DatabaseConfig struct {
	Host     string `yaml:"host"`
	Port     int    `yaml:"port"`
	User     string `yaml:"user"`
	Password string `yaml:"password"`
	DBName   string `yaml:"dbname"`
	SSLMode  string `yaml:"sslmode"`
}

type SchedulerConfig struct {
	Time string `yaml:"time"` // Format: "10:00"
}

type TelegramConfig struct {
	BotToken string `yaml:"bot_token"`
}

type DashboardConfig struct {
	Host string `yaml:"host"`
	Port int    `yaml:"port"`
}

func Load(path string) (*Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}

	var cfg Config
	if err := yaml.Unmarshal(data, &cfg); err != nil {
		return nil, err
	}

	// Set defaults
	if cfg.Scheduler.Time == "" {
		cfg.Scheduler.Time = "10:00"
	}
	if cfg.Database.Host == "" {
		cfg.Database.Host = "localhost"
	}
	if cfg.Database.Port == 0 {
		cfg.Database.Port = 5432
	}
	if cfg.Dashboard.Host == "" {
		cfg.Dashboard.Host = "0.0.0.0"
	}
	if cfg.Dashboard.Port == 0 {
		cfg.Dashboard.Port = 8080
	}
	if cfg.PythonParser.ScriptPath == "" {
		cfg.PythonParser.ScriptPath = "./bank_api_parser/main.py"
	}

	return &cfg, nil
}

func (c *SchedulerConfig) GetTime() (time.Time, error) {
	now := time.Now()
	loc, err := time.LoadLocation("Europe/Moscow")
	if err != nil {
		return time.Time{}, err
	}

	parsed, err := time.ParseInLocation("15:04", c.Time, loc)
	if err != nil {
		return time.Time{}, err
	}

	return time.Date(now.Year(), now.Month(), now.Day(), parsed.Hour(), parsed.Minute(), 0, 0, loc), nil
}
