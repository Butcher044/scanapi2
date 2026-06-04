package model

// Service представляет API сервис банка
type Service struct {
	Name string
	URL  string
}

// Method представляет метод API
type Method struct {
	Name        string
	HTTPMethod  string
	URL         string
	Description string
}

// Field представляет поле в ответе
type Field struct {
	Name        string
	Type        string
	Required    bool
	Description string
}

// ParseSnapshot структура снапшота из Python-парсера
type ParseSnapshot struct {
	Bank          string                   `json:"bank"`
	ParsedAt      string                   `json:"parsed_at"`
	Services      map[string][]APIMethod   `json:"services"`
	TotalServices int                      `json:"-"`
	TotalMethods  int                      `json:"-"`
}

// APIMethod представляет метод API из парсера
type APIMethod struct {
	Bank            string   `json:"bank"`
	ServiceName     string   `json:"service_name"`
	HTTPMethod      string   `json:"http_method"`
	Path            string   `json:"path"`
	Summary         string   `json:"summary"`
	Description     string   `json:"description"`
	Response200Fields []string `json:"response_200_fields"`
	URLOnPortal     string   `json:"url_on_portal"`
}