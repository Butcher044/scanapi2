package parser

import (
	"bytes"
	"context"
	"io"
	"log"
	"net/http"
	"strings"
	"time"

	"github.com/PuerkitoBio/goquery"

	"system-monitoring/internal/model"
)

// TBankParser парсер для Т-Банка
type TBankParser struct {
	client  *http.Client
	BaseURL string
}

func NewTBankParser() *TBankParser {
	return &TBankParser{
		client: &http.Client{
			Timeout: 30 * time.Second,
		},
		BaseURL: "https://developer.tbank.ru",
	}
}

func (p *TBankParser) Name() string {
	return "tbank"
}

// ParseServices парсит все API сервисы
func (p *TBankParser) ParseServices(ctx context.Context) ([]model.Service, error) {
	log.Printf("[TBank] Парсинг сервисов")

	// Важно: нужно перейти на /docs/api, где отображаются все методы
	targetURL := p.BaseURL + "/docs/api"
	log.Printf("[TBank] Запрашиваем: %s", targetURL)

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, targetURL, nil)
	if err != nil {
		log.Printf("[TBank] HTTP ошибка: %v, используем fallback", err)
		return p.fallbackServices(), nil
	}
	req.Header.Set("User-Agent", "Mozilla/5.0")

	resp, err := p.client.Do(req)
	if err != nil {
		log.Printf("[TBank] HTTP ошибка: %v, используем fallback", err)
		return p.fallbackServices(), nil
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		log.Printf("[TBank] HTTP статус: %d, используем fallback", resp.StatusCode)
		return p.fallbackServices(), nil
	}

	doc, err := goquery.NewDocumentFromReader(resp.Body)
	if err != nil {
		log.Printf("[TBank] Ошибка парсинга HTML: %v, используем fallback", err)
		return p.fallbackServices(), nil
	}

	// Debug: выводим все href с текстом
	log.Printf("[TBank] === Отладочный вывод ссылок ===")
	hrefs := make(map[string]string) // href -> text
	doc.Find("a[href]").Each(func(i int, s *goquery.Selection) {
		href, _ := s.Attr("href")
		text := strings.TrimSpace(s.Text())
		if href != "" && len(text) >= 3 {
			if _, ok := hrefs[href]; !ok {
				hrefs[href] = text
			}
		}
	})
	log.Printf("[TBank] Всего ссылок с текстом: %d", len(hrefs))
	count := 0
	for href, text := range hrefs {
		log.Printf("[TBank]   %s | %s", href, text)
		count++
		if count >= 30 {
			log.Printf("[TBank]   ... (еще %d)", len(hrefs)-count)
			break
		}
	}
	log.Printf("[TBank] === Конец отладочного вывода ===")

	var services []model.Service

	seen := make(map[string]bool)

	// Берем ВСЕ ссылки без фильтрации (минимальный мусор)
	doc.Find("a[href]").Each(func(i int, s *goquery.Selection) {
		href, exists := s.Attr("href")
		if !exists {
			return
		}

		text := strings.TrimSpace(s.Text())

		if text == "" || len(text) < 2 {
			return
		}

		// Пропускаем только явный мусор
		if strings.HasPrefix(href, "#") || strings.HasPrefix(href, "javascript:") {
			return
		}

		// Пропускаем дубликаты
		key := text + "|" + href
		if seen[key] {
			return
		}
		seen[key] = true

		if seen[key] {
			return
		}

		seen[key] = true

		url := href

		if !strings.HasPrefix(url, "http") {
			url = p.BaseURL + href
		}

		services = append(services, model.Service{
			Name: text,
			URL:  url,
		})

		log.Printf("[TBank] Найден сервис: %s -> %s", text, url)
	})

	if len(services) == 0 {
		return p.fallbackServices(), nil
	}

	log.Printf("[TBank] Найдено сервисов: %d", len(services))

	return services, nil
}

func (p *TBankParser) fallbackServices() []model.Service {
	log.Printf("[TBank] WARNING: fallback services")

	// Пробуем через простой HTTP (если chromedp недоступен)
	targetURL := p.BaseURL + "/docs/api"
	log.Printf("[TBank] Fallback: пробуем HTTP: %s", targetURL)

	req, _ := http.NewRequestWithContext(context.Background(), http.MethodGet, targetURL, nil)
	req.Header.Set("User-Agent", "Mozilla/5.0")
	resp, err := p.client.Do(req)
	if err == nil {
		body, _ := io.ReadAll(resp.Body)
		resp.Body.Close()
		if len(body) > 5000 {
			doc, _ := goquery.NewDocumentFromReader(bytes.NewReader(body))
			var services []model.Service
			seen := make(map[string]bool)
			doc.Find("a[href]").Each(func(i int, s *goquery.Selection) {
				href, _ := s.Attr("href")
				text := strings.TrimSpace(s.Text())
				if text == "" || len(text) < 3 {
					return
				}
				if !strings.HasPrefix(href, "/") || strings.HasPrefix(href, "//") {
					return
				}
				key := text
				if seen[key] {
					return
				}
				seen[key] = true
				services = append(services, model.Service{
					Name: text,
					URL:  p.BaseURL + href,
				})
			})
			if len(services) > 0 {
				log.Printf("[TBank] Fallback HTTP нашел: %d", len(services))
				return services
			}
		}
	}

	//Hardcoded fallback
	return []model.Service{
		{Name: "T-API", URL: "https://developer.tbank.ru/docs/api"},
		{Name: "T-Invest API", URL: "https://developer.tbank.ru/invest/intro/intro"},
		{Name: "Прием платежей", URL: "https://developer.tbank.ru/eacq/api"},
		{Name: "TQM", URL: "https://developer.tbank.ru/tqm/api"},
		{Name: "VoiceKit", URL: "https://developer.tbank.ru/voicekit/api/speech-recognition/grpc/"},
	}
}

func (p *TBankParser) fallbackMethods(serviceURL string) []model.Method {
	log.Printf("[TBank] WARNING: fallback methods")

	return []model.Method{
		{Name: "Получить аккаунты", URL: serviceURL, HTTPMethod: "GET"},
		{Name: "Получить позиции", URL: serviceURL, HTTPMethod: "GET"},
		{Name: "Создать ордер", URL: serviceURL, HTTPMethod: "POST"},
		{Name: "Отменить ордер", URL: serviceURL, HTTPMethod: "POST"},
		{Name: "Получить историю операций", URL: serviceURL, HTTPMethod: "GET"},
		{Name: "Получить стакан", URL: serviceURL, HTTPMethod: "GET"},
		{Name: "Получить инструменты", URL: serviceURL, HTTPMethod: "GET"},
		{Name: "Получить валюты", URL: serviceURL, HTTPMethod: "GET"},
	}
}

func (p *TBankParser) ParseMethods(
	ctx context.Context,
	serviceURL string,
) ([]model.Method, error) {

	log.Printf("[TBank] Парсинг методов: %s", serviceURL)

	// 1. Пробуем OpenAPI
	specURL, err := FindOpenAPISpecURL(ctx, p.client, serviceURL)
	if err == nil && specURL != "" {

		log.Printf("[TBank] Найден OpenAPI spec: %s", specURL)

		methods, _, err := ParseOpenAPISpec(
			ctx,
			p.client,
			specURL,
		)

		if err == nil && len(methods) > 0 {
			log.Printf(
				"[TBank] Методов из OpenAPI: %d",
				len(methods),
			)

			return methods, nil
		}

		log.Printf("[TBank] OpenAPI parsing failed: %v", err)
	}

	// 2. Fallback -> chromedp
	return p.parseMethodsChromedp(ctx, serviceURL)
}

func (p *TBankParser) parseMethodsChromedp(
	ctx context.Context,
	serviceURL string,
) ([]model.Method, error) {

	log.Printf("[TBank] Используем HTTP для: %s", serviceURL)

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, serviceURL, nil)
	if err != nil {
		log.Printf("[TBank] HTTP ошибка: %v", err)
		return p.fallbackMethods(serviceURL), nil
	}
	req.Header.Set("User-Agent", "Mozilla/5.0")

	resp, err := p.client.Do(req)
	if err != nil {
		log.Printf("[TBank] HTTP ошибка: %v", err)
		return p.fallbackMethods(serviceURL), nil
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		log.Printf("[TBank] HTTP статус: %d", resp.StatusCode)
		return p.fallbackMethods(serviceURL), nil
	}

	doc, err := goquery.NewDocumentFromReader(resp.Body)
	if err != nil {
		log.Printf("[TBank] Ошибка парсинга: %v", err)
		return p.fallbackMethods(serviceURL), nil
	}

	var methods []model.Method

	seen := make(map[string]bool)

	// Debug: сколько li.theme-doc-sidebar-item-category
	categoryCount := doc.Find("li.theme-doc-sidebar-item-category").Length()
	log.Printf("[TBank] Найдено категорий: %d", categoryCount)

	// Debug: сколько li.api-method
	apiMethodCount := doc.Find("li.api-method").Length()
	log.Printf("[TBank] Найдено li.api-method: %d", apiMethodCount)

	// Debug: все li с классом содержащим api
	doc.Find("li[class*='api']").Each(func(i int, s *goquery.Selection) {
		cls, _ := s.Attr("class")
		log.Printf("[TBank] li[class*='api'] #%d: %s", i, cls)
	})

	// Categories
	doc.Find("li.theme-doc-sidebar-item-category").
		Each(func(i int, category *goquery.Selection) {

			//groupName := strings.TrimSpace(
			//	category.Find("> div a.menu__link").First().Text(),
			//)

			// Methods
			category.Find("li.api-method").
				Each(func(j int, methodSel *goquery.Selection) {

					link := methodSel.Find("a")

					name := strings.TrimSpace(link.Text())

					if name == "" {
						return
					}

					href, exists := link.Attr("href")
					if !exists {
						return
					}

					key := name + "|" + href

					if seen[key] {
						return
					}

					seen[key] = true

					url := href

					if !strings.HasPrefix(url, "http") {
						url = p.BaseURL + href
					}

					classAttr, _ := methodSel.Attr("class")

					httpMethod := detectHTTPMethod(classAttr)

					methods = append(methods, model.Method{
						Name:        extractMethodName(name),
						Description: extractDescription(name),
						HTTPMethod:  httpMethod,
						URL:         url,
						//Service:     groupName,
					})

					log.Printf(
						"[TBank] Метод [%s] %s -> %s",
						httpMethod,
						name,
						url,
					)
				})
		})

	// Fallback: если li.api-method не найдено, пробуем другие селекторы
	if len(methods) == 0 {
		log.Printf("[TBank] Методы не найдены через li.api-method, пробуем другие селекторы")

		// Ищем все ссылки в sidebar
		doc.Find("nav a[href], aside a[href], div[class*='side'] a[href], ul[class*='menu'] a[href]").Each(func(i int, s *goquery.Selection) {
			href, _ := s.Attr("href")
			text := strings.TrimSpace(s.Text())

			if text == "" || len(text) < 3 {
				return
			}

			// Пропускаем нерелевантные - введение, статьи и т.д.
			lowerHref := strings.ToLower(href)
			lowerText := strings.ToLower(text)
			if strings.Contains(lowerHref, "intro") || strings.Contains(lowerHref, "about") ||
				strings.Contains(lowerHref, "start") || strings.Contains(lowerHref, "tutorial") ||
				strings.Contains(lowerHref, "/docs/intro") || strings.Contains(lowerText, "введение") ||
				strings.Contains(lowerText, "подключение") || strings.Contains(lowerText, "начало") ||
				strings.Contains(lowerText, "интеграция") {
				return
			}

			key := text
			if seen[key] {
				return
			}
			seen[key] = true

			url := href
			if !strings.HasPrefix(url, "http") {
				url = p.BaseURL + href
			}

			// Определяем HTTP метод
			httpMethod := "GET"
			if strings.Contains(lowerText, "создать") || strings.Contains(lowerText, "добавить") ||
				strings.Contains(lowerText, "create") || strings.Contains(lowerText, "post") {
				httpMethod = "POST"
			} else if strings.Contains(lowerText, "удалить") || strings.Contains(lowerText, "delete") {
				httpMethod = "DELETE"
			}

			log.Printf("[TBank][Fallback] Метод: %s %s", httpMethod, text)

			methods = append(methods, model.Method{
				Name:       text,
				HTTPMethod: httpMethod,
				URL:        url,
			})
		})
	}

	if len(methods) == 0 {
		log.Printf("[TBank] Методы не найдены, используем fallback")
		return []model.Method{
			{Name: "Получить аккаунты", URL: serviceURL, HTTPMethod: "GET"},
			{Name: "Получить позиции", URL: serviceURL, HTTPMethod: "GET"},
			{Name: "Создать ордер", URL: serviceURL, HTTPMethod: "POST"},
			{Name: "Отменить ордер", URL: serviceURL, HTTPMethod: "POST"},
			{Name: "Получить историю операций", URL: serviceURL, HTTPMethod: "GET"},
			{Name: "Получить стакан", URL: serviceURL, HTTPMethod: "GET"},
			{Name: "Получить инструменты", URL: serviceURL, HTTPMethod: "GET"},
			{Name: "Получить валюты", URL: serviceURL, HTTPMethod: "GET"},
		}, nil
	}

	log.Printf("[TBank] Найдено методов: %d", len(methods))

	return methods, nil
}

func detectHTTPMethod(classAttr string) string {
	classAttr = strings.ToLower(classAttr)

	switch {
	case strings.Contains(classAttr, "post"):
		return "POST"

	case strings.Contains(classAttr, "get"):
		return "GET"

	case strings.Contains(classAttr, "put"):
		return "PUT"

	case strings.Contains(classAttr, "delete"):
		return "DELETE"

	case strings.Contains(classAttr, "patch"):
		return "PATCH"

	default:
		return "UNKNOWN"
	}
}

func extractMethodName(text string) string {
	parts := strings.Split(text, "—")

	if len(parts) == 0 {
		return strings.TrimSpace(text)
	}

	return strings.TrimSpace(parts[0])
}

func extractDescription(text string) string {
	parts := strings.Split(text, "—")

	if len(parts) < 2 {
		return ""
	}

	return strings.TrimSpace(parts[1])
}

func (p *TBankParser) ParseFields(
	ctx context.Context,
	methodURL string,
) ([]model.Field, error) {

	if methodURL == "" {
		return nil, nil
	}

	req, err := http.NewRequestWithContext(
		ctx,
		http.MethodGet,
		methodURL,
		nil,
	)

	if err != nil {
		return nil, err
	}

	req.Header.Set(
		"User-Agent",
		"Mozilla/5.0",
	)

	resp, err := p.client.Do(req)
	if err != nil {
		return nil, err
	}

	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, nil
	}

	doc, err := goquery.NewDocumentFromReader(resp.Body)
	if err != nil {
		return nil, err
	}

	var fields []model.Field

	doc.Find(`
		table,
		div[class*='schema'],
		div[class*='field'],
		div[class*='property']
	`).Each(func(i int, s *goquery.Selection) {

		s.Find("tr, li, div").
			Each(func(j int, sel *goquery.Selection) {

				text := strings.TrimSpace(sel.Text())

				if text == "" {
					return
				}

				lines := strings.Split(text, "\n")

				for _, line := range lines {

					line = strings.TrimSpace(line)

					if line == "" {
						continue
					}

					parts := strings.Fields(line)

					if len(parts) == 0 {
						continue
					}

					fieldName := strings.Trim(
						parts[0],
						"*{}",
					)

					if fieldName == "" {
						continue
					}

					required :=
						strings.Contains(
							strings.ToLower(line),
							"required",
						)

					fields = append(fields, model.Field{
						Name:        fieldName,
						Required:    required,
						Description: strings.Join(parts[1:], " "),
					})
				}
			})
	})

	return fields, nil
}
