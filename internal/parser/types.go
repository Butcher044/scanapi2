package parser

import (
	"context"
	"encoding/json"
	"io"
	"log"
	"net/http"
	"regexp"
	"strings"
	"system-monitoring/internal/model"
)

// BankParser интерфейс для парсеров банков
type BankParser interface {
	Name() string
	ParseServices(ctx context.Context) ([]model.Service, error)
	ParseMethods(ctx context.Context, serviceURL string) ([]model.Method, error)
	ParseFields(ctx context.Context, methodURL string) ([]model.Field, error)
}

// OpenAPISpec представляет структуру OpenAPI спецификации
type OpenAPISpec struct {
	Paths map[string]map[string]struct {
		Summary     string `json:"summary"`
		Description string `json:"description"`
		OperationID string `json:"operationId"`
		Parameters  []struct {
			Name        string `json:"name"`
			In          string `json:"in"`
			Required    bool   `json:"required"`
			Description string `json:"description"`
			Schema      struct {
				Type string `json:"type"`
			} `json:"schema"`
		} `json:"parameters"`
		Responses map[string]struct {
			Description string `json:"description"`
			Content     map[string]struct {
				Schema struct {
					Properties map[string]struct {
						Type        string   `json:"type"`
						Description string   `json:"description"`
						Required    []string `json:"required"`
						Properties  map[string]struct {
							Type string `json:"type"`
						} `json:"properties"`
					} `json:"properties"`
				} `json:"schema"`
			} `json:"content"`
		} `json:"responses"`
	} `json:"paths"`
	Info struct {
		Title   string `json:"title"`
		Version string `json:"version"`
	} `json:"info"`
}

// FindOpenAPISpecURL ищет URL OpenAPI spec на странице документации
func FindOpenAPISpecURL(ctx context.Context, client *http.Client, pageURL string) (string, error) {
	log.Printf("[OpenAPI] Поиск spec для: %s", pageURL)

	// Добавляем User-Agent
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, pageURL, nil)
	if err != nil {
		return "", err
	}
	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

	resp, err := client.Do(req)
	if err != nil {
		log.Printf("[OpenAPI] Ошибка запроса: %v", err)
		return "", err
	}
	defer resp.Body.Close()

	log.Printf("[OpenAPI] Статус ответа: %d", resp.StatusCode)

	if resp.StatusCode != http.StatusOK {
		// Пробуем типовые URL
		log.Printf("[OpenAPI] Статус не 200, пробуем типовые URL")
		return tryCommonSpecURLs(ctx, client, pageURL)
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", err
	}
	html := string(body)

	log.Printf("[OpenAPI] Получен HTML, длина: %d байт", len(html))

	// Паттерны для поиска OpenAPI spec URL
	patterns := []string{
		`"swaggerUrl"\s*[:=]\s*"([^"]+\.json)"`,
		`"openapiUrl"\s*[:=]\s*"([^"]+\.json)"`,
		`"url"\s*[:=]\s*"([^"]*openapi[^"]*\.json)"`,
		`"url"\s*[:=]\s*"([^"]*swagger[^"]*\.json)"`,
		`href="([^"]*openapi[^"]*\.json)"`,
		`href="([^"]*swagger[^"]*\.json)"`,
		`window\.openapi\s*=\s*"([^"]+\.json)"`,
		`window\.swagger\s*=\s*"([^"]+\.json)"`,
		`url\s*:\s*'([^']*openapi[^']*\.json)'`,
		`url\s*:\s*'([^']*swagger[^']*\.json)'`,
		`data-src="([^"]*openapi[^"]*\.json)"`,
		`data-src="([^"]*swagger[^"]*\.json)"`,
		`spec-url="([^"]+)"`,
		`swaggerJson\s*:\s*"([^"]+\.json)"`,
	}

	for _, pattern := range patterns {
		re := regexp.MustCompile(pattern)
		matches := re.FindStringSubmatch(html)
		if len(matches) > 1 {
			url := matches[1]
			log.Printf("[OpenAPI] Найден URL по паттерну: %s", url)
			if !strings.HasPrefix(url, "http") {
				url = resolveURL(pageURL, url)
			}
			// Проверяем, что URL доступен
			if isValidSpecURL(ctx, client, url) {
				log.Printf("[OpenAPI] Найден валидный spec: %s", url)
				return url, nil
			}
		}
	}

	// Пробуем типовые URL
	log.Printf("[OpenAPI] Паттерны не сработали, пробуем типовые URL")
	return tryCommonSpecURLs(ctx, client, pageURL)
}

// tryCommonSpecURLs пробует стандартные пути к OpenAPI spec
func tryCommonSpecURLs(ctx context.Context, client *http.Client, pageURL string) (string, error) {
	// Извлекаем базовый URL
	baseURL := pageURL
	if idx := strings.LastIndex(baseURL, "/docs/"); idx > 0 {
		baseURL = baseURL[:idx+5] // /docs/
	} else if idx := strings.LastIndex(baseURL, "/products/"); idx > 0 {
		baseURL = baseURL[:idx+9] // /products/
	} else if idx := strings.LastIndex(baseURL, "/overview"); idx > 0 {
		baseURL = baseURL[:idx]
	}

	log.Printf("[OpenAPI] Базовый URL: %s", baseURL)

	// Типовые пути к spec
	commonPaths := []string{
		"/openapi.json",
		"/swagger.json",
		"/api/openapi.json",
		"/api/swagger.json",
		"/docs/openapi.json",
		"/docs/swagger.json",
		"/swagger-ui/openapi.json",
		"/swagger-ui/swagger.json",
		"/api/v1/openapi.json",
		"/api/v1/swagger.json",
	}

	for _, path := range commonPaths {
		specURL := baseURL + path
		log.Printf("[OpenAPI] Пробуем: %s", specURL)
		if isValidSpecURL(ctx, client, specURL) {
			log.Printf("[OpenAPI] Найден spec по базовому URL: %s", specURL)
			return specURL, nil
		}
	}

	// Пробуем найти в том же домене
	domainPaths := []string{
		"/openapi.json",
		"/swagger.json",
	}
	// Извлекаем домен
	parts := strings.SplitN(pageURL, "/", 4)
	if len(parts) >= 3 {
		domain := parts[0] + "//" + parts[2]
		log.Printf("[OpenAPI] Домен: %s", domain)
		for _, path := range domainPaths {
			specURL := domain + path
			log.Printf("[OpenAPI] Пробуем домен: %s", specURL)
			if isValidSpecURL(ctx, client, specURL) {
				log.Printf("[OpenAPI] Найден spec по домену: %s", specURL)
				return specURL, nil
			}
		}
	}

	log.Printf("[OpenAPI] Spec не найден")
	return "", nil
}

// isValidSpecURL проверяет, что URL ведет к валидному JSON
func isValidSpecURL(ctx context.Context, client *http.Client, url string) bool {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return false
	}
	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

	resp, err := client.Do(req)
	if err != nil {
		return false
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return false
	}

	// Проверяем, что это JSON и содержит "paths" или "openapi"
	body, err := io.ReadAll(io.LimitReader(resp.Body, 1024))
	if err != nil {
		return false
	}

	content := string(body)
	return strings.Contains(content, `"paths"`) || strings.Contains(content, `"openapi"`)
}

// resolveURL преобразует относительный URL в абсолютный
func resolveURL(baseURL, relativeURL string) string {
	if strings.HasPrefix(relativeURL, "http") {
		return relativeURL
	}

	if strings.HasPrefix(relativeURL, "/") {
		parts := strings.SplitN(baseURL, "/", 4)
		if len(parts) >= 3 {
			return parts[0] + "//" + parts[2] + relativeURL
		}
	}

	// Текущая директория
	lastSlash := strings.LastIndex(baseURL, "/")
	if lastSlash > 0 {
		return baseURL[:lastSlash+1] + relativeURL
	}

	return baseURL + "/" + relativeURL
}

// ParseOpenAPISpec парсит OpenAPI spec и извлекает методы и поля
func ParseOpenAPISpec(ctx context.Context, client *http.Client, specURL string) ([]model.Method, []model.Field, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, specURL, nil)
	if err != nil {
		return nil, nil, err
	}

	resp, err := client.Do(req)
	if err != nil {
		return nil, nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, nil, nil
	}

	var spec OpenAPISpec
	if err := json.NewDecoder(resp.Body).Decode(&spec); err != nil {
		return nil, nil, err
	}

	var methods []model.Method
	var fields []model.Field

	for path, pathItem := range spec.Paths {
		for httpMethod, operation := range pathItem {
			if httpMethod == "parameters" || httpMethod == "summary" || httpMethod == "description" {
				continue
			}

			method := model.Method{
				Name:        operation.Summary,
				HTTPMethod:  strings.ToUpper(httpMethod),
				URL:         specURL + "#" + path + "-" + httpMethod,
				Description: operation.Description,
			}

			if method.Name == "" {
				method.Name = httpMethod + " " + path
			}

			methods = append(methods, method)

			// Парсим параметры
			for _, param := range operation.Parameters {
				fields = append(fields, model.Field{
					Name:        param.Name,
					Type:        param.Schema.Type,
					Required:    param.Required,
					Description: param.Description,
				})
			}

			// Парсим поля из response schema (200 OK)
			if response, ok := operation.Responses["200"]; ok {
				if content, ok := response.Content["application/json"]; ok {
					parseSchemaFields("", content.Schema.Properties, &fields)
				}
			}
		}
	}

	return methods, fields, nil
}

func parseSchemaFields(prefix string, properties any, fields *[]model.Field) {
	if properties == nil {
		return
	}
	props, ok := properties.(map[string]any)
	if !ok {
		return
	}
	for name, prop := range props {
		fieldName := name
		if prefix != "" {
			fieldName = prefix + "." + name
		}
		propMap, ok := prop.(map[string]any)
		if !ok {
			continue
		}
		*fields = append(*fields, model.Field{
			Name: fieldName,
			Type: "",
		})
		if t, ok := propMap["type"].(string); ok {
			(*fields)[len(*fields)-1].Type = t
		}
		// Рекурсивно обрабатываем вложенные объекты
		if nested, ok := propMap["properties"].(map[string]any); ok {
			parseSchemaFields(fieldName, nested, fields)
		}
	}
}
