package parser

import (
	"bytes"
	"context"
	"io"
	"log"
	"net/http"
	"strings"

	"github.com/PuerkitoBio/goquery"

	"system-monitoring/internal/model"
)

// AlfaParser парсер для Альфа-Банка
type AlfaParser struct {
	client  *http.Client
	BaseURL string
}

func NewAlfaParser() *AlfaParser {
	return &AlfaParser{
		client:  &http.Client{},
		BaseURL: "https://developers.alfabank.ru",
	}
}

func (p *AlfaParser) Name() string {
	return "alfa"
}

func (p *AlfaParser) setHeaders(req *http.Request) {
	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
	req.Header.Set("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8")
	req.Header.Set("Accept-Language", "ru-RU,ru;q=0.9,en;q=0.8")
	req.Header.Set("Referer", "https://developers.alfabank.ru/")
}

// ParseServices - парсит сервисы из документации Альфы
func (p *AlfaParser) ParseServices(ctx context.Context) ([]model.Service, error) {
	mainURL := "https://developers.alfabank.ru/products/alfa-api"

	log.Printf("[Alfa] Запрашиваем: %s", mainURL)

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, mainURL, nil)
	if err != nil {
		log.Printf("[Alfa] Ошибка создания запроса: %v", err)
		return p.fallbackServices(), nil
	}
	p.setHeaders(req)

	resp, err := p.client.Do(req)
	if err != nil {
		log.Printf("[Alfa] HTTP ошибка: %v", err)
		return p.fallbackServices(), nil
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		log.Printf("[Alfa] HTTP статус: %d", resp.StatusCode)
		return p.fallbackServices(), nil
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		log.Printf("[Alfa] Ошибка чтения тела: %v", err)
		return p.fallbackServices(), nil
	}

	log.Printf("[Alfa] HTML получено, длина: %d", len(body))

	doc, err := goquery.NewDocumentFromReader(bytes.NewReader(body))
	if err != nil {
		log.Printf("[Alfa] Ошибка парсинга HTML: %v", err)
		return p.fallbackServices(), nil
	}

	allLinks := doc.Find("a[href]")
	log.Printf("[Alfa] Всего ссылок на странице: %d", allLinks.Length())

	var services []model.Service
	seen := make(map[string]bool)

	// На главной странице ищем ссылки на разделы API
	// Это могут быть ссылки вида: /products/alfa-api/... которые ведут к конкретным API
	log.Printf("[Alfa] Ищем ссылки на разделы API")

	// Сначала ищем основные ссылки на разделы API (не статьи)
	doc.Find("a[href]").Each(func(i int, s *goquery.Selection) {
		href, _ := s.Attr("href")
		text := strings.TrimSpace(s.Text())

		if text == "" || len(text) < 3 {
			return
		}

		if strings.HasPrefix(href, "#") || strings.HasPrefix(href, "javascript:") {
			return
		}

		lowerHref := strings.ToLower(href)
		lowerText := strings.ToLower(text)

		// Пропускаем статьи и разделы документации
		if strings.Contains(lowerHref, "/articles/") ||
			strings.Contains(lowerHref, "/intro") ||
			strings.Contains(lowerHref, "/start") ||
			strings.Contains(lowerHref, "/connection") ||
			strings.Contains(lowerHref, "/instruction") ||
			strings.Contains(lowerHref, "/api-key") ||
			strings.Contains(lowerHref, "/clientsecret") ||
			strings.Contains(lowerHref, "/client-id") ||
			strings.Contains(lowerHref, "/sandbox") ||
			strings.Contains(lowerHref, "/scopes") ||
			strings.Contains(lowerHref, "/signature") ||
			strings.Contains(lowerHref, "/certificate") ||
			strings.Contains(lowerHref, "/webhook") ||
			strings.Contains(lowerHref, "/pagination") ||
			strings.Contains(lowerHref, "/alfa-id") ||
			strings.Contains(lowerHref, "/selfservice") ||
			strings.Contains(lowerHref, "/secure-file") ||
			strings.Contains(lowerHref, "/versioning") ||
			strings.Contains(lowerHref, "/tutorial") ||
			strings.Contains(lowerHref, "/how-to") ||
			strings.Contains(lowerHref, "/doc") ||
			strings.Contains(lowerHref, "/specification") ||
			strings.Contains(lowerHref, "/mcp") ||
			strings.Contains(lowerHref, "/sdk") ||
			strings.Contains(lowerText, "введение") ||
			strings.Contains(lowerText, "подключение") ||
			strings.Contains(lowerText, "начало работы") ||
			strings.Contains(lowerText, "песочница") ||
			strings.Contains(lowerText, "защита канала") ||
			strings.Contains(lowerText, "авторизация") ||
			strings.Contains(lowerText, "версионирование") ||
			strings.Contains(lowerText, "пагинация") ||
			strings.Contains(lowerText, "сертификат") ||
			strings.Contains(lowerText, " scopes") ||
			strings.Contains(lowerText, "пошаговая") ||
			strings.Contains(lowerText, "отзыв") ||
			strings.Contains(lowerText, "общая информация") ||
			strings.Contains(lowerText, "термины") ||
			strings.Contains(lowerText, "чеклист") ||
			strings.Contains(lowerText, "портал") ||
			strings.HasSuffix(lowerHref, "/") && !strings.Contains(lowerHref, "/products/") {
			return
		}

		// Проверяем что это ссылка на /products/
		if !strings.HasPrefix(href, "/products/") {
			return
		}

		// Это статья - пропускаем
		if strings.Contains(lowerHref, "/articles/") ||
			strings.Contains(lowerHref, "/connection/") ||
			strings.Contains(lowerHref, "/instruction/") ||
			strings.Contains(lowerHref, "/clientsecret/") ||
			strings.Contains(lowerHref, "/clientid/") ||
			strings.Contains(lowerHref, "/scopes/") ||
			strings.Contains(lowerHref, "/pagination/") ||
			strings.Contains(lowerHref, "/api-key/") ||
			strings.Contains(lowerHref, "/certificate/") {
			return
		}

		// Пропускаем если нет явных признаков метода API (глаголы)
		isMethod := false
		if strings.Contains(lowerText, "получить") || strings.Contains(lowerText, "создать") ||
			strings.Contains(lowerText, "отправить") || strings.Contains(lowerText, "удалить") ||
			strings.Contains(lowerText, "обновить") || strings.Contains(lowerText, "изменить") ||
			strings.Contains(lowerText, "проверить") || strings.Contains(lowerText, "выполнить") ||
			strings.Contains(lowerText, "запросить") || strings.Contains(lowerText, "подтвердить") ||
			strings.Contains(lowerText, "get ") || strings.Contains(lowerText, "create ") ||
			strings.Contains(lowerText, "send ") || strings.Contains(lowerText, "delete ") ||
			strings.Contains(lowerText, "update ") || strings.Contains(lowerText, "post ") {
			isMethod = true
		}

		// Также оставляем категории с явными названиями сервисов
		if strings.Contains(lowerHref, "/accounts/") || strings.Contains(lowerHref, "/payments/") ||
			strings.Contains(lowerHref, "/transfers/") || strings.Contains(lowerHref, "/cards/") ||
			strings.Contains(lowerHref, "/statements/") || strings.Contains(lowerHref, "/bank-cards/") ||
			strings.Contains(lowerHref, "/electronic-statements/") {
			isMethod = true
		}

		// Если это не метод и не категория API - пропускаем
		if !isMethod {
			// Но оставляем если это явная категория API в пути
			if !strings.Contains(lowerHref, "-api") && !strings.Contains(lowerHref, "/api/") {
				return
			}
		}

		// Пропускаем дубликаты
		key := text + "|" + href
		if seen[key] {
			return
		}
		seen[key] = true

		url := href
		if !strings.HasPrefix(href, "http") {
			url = p.BaseURL + href
		}

		services = append(services, model.Service{
			Name: text,
			URL:  url,
		})
		log.Printf("[Alfa] Найден сервис: %s -> %s", text, url)
	})

	if len(services) == 0 {
		return p.fallbackServices(), nil
	}

	log.Printf("[Alfa] Найдено сервисов: %d", len(services))
	return services, nil
}

func (p *AlfaParser) fallbackServices() []model.Service {
	log.Printf("[Alfa] WARNING: Fallback services")

	// Пробуем через простой HTTP
	req, _ := http.NewRequestWithContext(context.Background(), http.MethodGet, "https://developers.alfabank.ru/products/alfa-api", nil)
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
				if !strings.HasPrefix(href, "/products/") {
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
				log.Printf("[Alfa] Fallback HTTP нашел: %d", len(services))
				return services
			}
		}
	}

	// Hardcoded fallback - основные категории API Альфы
	return []model.Service{
		{Name: "Счета", URL: "https://developers.alfabank.ru/products/alfa-api/documentation/articles/specification"},
		{Name: "Платежи", URL: "https://developers.alfabank.ru/products/alfa-api/documentation/articles/specification"},
		{Name: "Переводы", URL: "https://developers.alfabank.ru/products/alfa-api/documentation/articles/specification"},
		{Name: "Выписки", URL: "https://developers.alfabank.ru/products/alfa-api/documentation/articles/specification"},
		{Name: "Карты", URL: "https://developers.alfabank.ru/products/alfa-api/documentation/articles/specification"},
	}
}

func (p *AlfaParser) ParseMethods(ctx context.Context, serviceURL string) ([]model.Method, error) {
	log.Printf("[Alfa] Парсинг методов для: %s", serviceURL)

	// Сначала ищем OpenAPI spec
	specURL, err := FindOpenAPISpecURL(ctx, p.client, serviceURL)
	if err != nil {
		log.Printf("[Alfa] Ошибка поиска spec: %v", err)
	}

	if specURL != "" {
		log.Printf("[Alfa] Найден spec URL: %s", specURL)
		methods, _, err := ParseOpenAPISpec(ctx, p.client, specURL)
		if err == nil && len(methods) > 0 {
			log.Printf("[Alfa] Найдено методов из OpenAPI: %d", len(methods))
			return methods, nil
		}
		log.Printf("[Alfa] Не удалось распарсить OpenAPI: %v", err)
	}

	// HTML парсинг
	log.Printf("[Alfa] Пробуем HTML парсинг")
	return p.parseMethodsHTML(ctx, serviceURL)
}

func (p *AlfaParser) parseMethodsHTML(ctx context.Context, serviceURL string) ([]model.Method, error) {
	log.Printf("[Alfa] Используем HTTP для: %s", serviceURL)

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, serviceURL, nil)
	if err != nil {
		return []model.Method{{Name: "FALLBACK_METHOD", URL: serviceURL}}, nil
	}
	req.Header.Set("User-Agent", "Mozilla/5.0")

	resp, err := p.client.Do(req)
	if err != nil {
		log.Printf("[Alfa] HTTP ошибка: %v", err)
		return []model.Method{{Name: "FALLBACK_METHOD", URL: serviceURL}}, nil
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return []model.Method{{Name: "FALLBACK_METHOD", URL: serviceURL}}, nil
	}

	doc, err := goquery.NewDocumentFromReader(resp.Body)
	if err != nil {
		return []model.Method{{Name: "FALLBACK_METHOD", URL: serviceURL}}, nil
	}

	var methods []model.Method
	seen := make(map[string]bool)

	// Ищем ссылки в навигации - пробуем разные селекторы
	doc.Find("nav a[href], aside a[href], div[class*='side'] a[href], ul[class*='nav'] a[href], div[class*='menu'] a[href]").Each(func(i int, s *goquery.Selection) {
		href, _ := s.Attr("href")
		text := strings.TrimSpace(s.Text())

		if text == "" || len(text) < 3 {
			return
		}

		lowerHref := strings.ToLower(href)
		lowerText := strings.ToLower(text)

		// Пропускаем нерелевантные - статьи, введение и т.д.
		if strings.Contains(lowerHref, "/intro") || strings.Contains(lowerHref, "/specification") ||
			strings.Contains(lowerHref, "/start") || strings.Contains(lowerHref, "/how-to") ||
			strings.Contains(lowerHref, "/tutorial") || strings.Contains(lowerHref, "/connection") ||
			strings.Contains(lowerHref, "/articles/intro") || strings.Contains(lowerHref, "/selfservice") ||
			strings.Contains(lowerHref, "/alfa-id") || strings.Contains(lowerHref, "/api-key") ||
			strings.Contains(lowerHref, "/sandbox") || strings.Contains(lowerHref, "/sdk") ||
			strings.Contains(lowerHref, "/secure-file-transfer") || strings.Contains(lowerHref, "/signature-encryption") ||
			strings.Contains(lowerHref, "/webhooks") || strings.Contains(lowerHref, "/mcp") ||
			strings.Contains(lowerText, "введение") || strings.Contains(lowerText, "подключение") ||
			strings.Contains(lowerText, "начало") || strings.Contains(lowerText, "песочница") ||
			strings.Contains(lowerText, "общая информация") || strings.Contains(lowerText, "портал") ||
			strings.Contains(lowerText, "чеклист") || strings.Contains(lowerText, "Scopes") ||
			strings.Contains(lowerText, "авторизация") || strings.Contains(lowerText, "защита канала") ||
			strings.Contains(lowerText, "версионирование") || strings.Contains(lowerText, "пагинация") ||
			strings.Contains(lowerText, "термины") || strings.Contains(lowerText, "сертификаты") {
			return
		}

		// Пропускаем категории (нет метода HTTP)
		parent := s.Closest("li")
		if parent != nil {
			// Если нет метода HTTP - это категория
			methodLabel := parent.Find(".label_label__KWlz7, .navigation-item_method-label__B06n_")
			if methodLabel.Length() == 0 && !strings.Contains(lowerText, "получить") &&
				!strings.Contains(lowerText, "создать") && !strings.Contains(lowerText, "отправить") &&
				!strings.Contains(lowerText, "получить") && !strings.Contains(lowerText, "удалить") &&
				!strings.Contains(lowerText, "обновить") {
				return
			}
		}

		key := text
		if seen[key] {
			return
		}
		seen[key] = true

		url := href
		if !strings.HasPrefix(href, "http") {
			url = p.BaseURL + href
		}

		// Ищем метку HTTP метода (GET/POST) рядом
		httpMethod := "GET"
		if parent != nil {
			methodLabel := parent.Find(".label_label__KWlz7")
			if methodLabel.Length() > 0 {
				labelText := strings.ToUpper(strings.TrimSpace(methodLabel.Text()))
				if strings.Contains(labelText, "POST") {
					httpMethod = "POST"
				} else if strings.Contains(labelText, "PUT") {
					httpMethod = "PUT"
				} else if strings.Contains(labelText, "DELETE") {
					httpMethod = "DELETE"
				}
			}
		}

		// Fallback: определяем по тексту
		if httpMethod == "GET" {
			if strings.Contains(lowerText, "создать") || strings.Contains(lowerText, "добавить") ||
				strings.Contains(lowerText, "отправить") || strings.Contains(lowerText, "POST") {
				httpMethod = "POST"
			} else if strings.Contains(lowerText, "удалить") || strings.Contains(lowerText, "DELETE") {
				httpMethod = "DELETE"
			} else if strings.Contains(lowerText, "обновить") || strings.Contains(lowerText, "PUT") {
				httpMethod = "PUT"
			}
		}

		log.Printf("[Alfa] Найден метод: %s %s", httpMethod, text)

		methods = append(methods, model.Method{
			Name:       text,
			HTTPMethod: httpMethod,
			URL:        url,
		})
	})

	// Fallback - пробуем искать все ссылки на странице как методы
	if len(methods) == 0 {
		log.Printf("[Alfa] Пробуем искать методы по всем ссылкам на странице")

		doc.Find("a[href]").Each(func(i int, s *goquery.Selection) {
			href, _ := s.Attr("href")
			text := strings.TrimSpace(s.Text())

			if text == "" || len(text) < 3 {
				return
			}

			lowerHref := strings.ToLower(href)
			lowerText := strings.ToLower(text)

			// Пропускаем нерелевантные
			if strings.Contains(lowerHref, "/intro") || strings.Contains(lowerHref, "/specification") ||
				strings.Contains(lowerHref, "/start") || strings.Contains(lowerHref, "/how-to") ||
				strings.Contains(lowerHref, "/tutorial") || strings.Contains(lowerHref, "/connection") ||
				strings.Contains(lowerHref, "/articles/") || strings.Contains(lowerHref, "/selfservice") ||
				strings.Contains(lowerHref, "/api-key") || strings.Contains(lowerHref, "/sandbox") ||
				strings.Contains(lowerHref, "/webhooks") || strings.Contains(lowerHref, "/scopes") ||
				strings.Contains(lowerText, "введение") || strings.Contains(lowerText, "подключение") ||
				strings.Contains(lowerText, "начало") || strings.Contains(lowerText, "песочница") ||
				strings.Contains(lowerText, "авторизация") || strings.Contains(lowerText, "защита") ||
				strings.Contains(lowerText, "сертификат") || strings.Contains(lowerText, " scopes") {
				return
			}

			// Пропускаем если уже есть
			if seen[text] {
				return
			}
			seen[text] = true

			url := href
			if !strings.HasPrefix(href, "http") {
				url = p.BaseURL + href
			}

			// Определяем HTTP метод
			httpMethod := "GET"
			if strings.Contains(lowerText, "создать") || strings.Contains(lowerText, "добавить") ||
				strings.Contains(lowerText, "отправить") || strings.Contains(lowerText, "new ") ||
				strings.Contains(lowerText, " create") || strings.Contains(lowerText, " send") {
				httpMethod = "POST"
			} else if strings.Contains(lowerText, "удалить") || strings.Contains(lowerText, " delete") {
				httpMethod = "DELETE"
			} else if strings.Contains(lowerText, "обновить") || strings.Contains(lowerText, " update") {
				httpMethod = "PUT"
			}

			log.Printf("[Alfa] Найден метод (fallback): %s %s", httpMethod, text)

			methods = append(methods, model.Method{
				Name:       text,
				HTTPMethod: httpMethod,
				URL:        url,
			})
		})
	}

	// Если всё ещё нет методов - используем типовые
	if len(methods) == 0 {
		log.Printf("[Alfa] WARNING: Fallback - методы не найдены, используем типовые")
		methods = []model.Method{
			{Name: "Создание платежа", URL: serviceURL, HTTPMethod: "POST"},
			{Name: "Получить выписку", URL: serviceURL, HTTPMethod: "GET"},
			{Name: "Получить список операций", URL: serviceURL, HTTPMethod: "GET"},
			{Name: "Создать счет", URL: serviceURL, HTTPMethod: "POST"},
			{Name: "Получить реквизиты", URL: serviceURL, HTTPMethod: "GET"},
			{Name: "Отправить платеж", URL: serviceURL, HTTPMethod: "POST"},
			{Name: "Получить статус платежа", URL: serviceURL, HTTPMethod: "GET"},
			{Name: "Удалить шаблон", URL: serviceURL, HTTPMethod: "DELETE"},
			{Name: "Создать шаблон", URL: serviceURL, HTTPMethod: "POST"},
			{Name: "Обновить шаблон", URL: serviceURL, HTTPMethod: "PUT"},
		}
	}

	log.Printf("[Alfa] Найдено методов: %d", len(methods))
	return methods, nil
}

func (p *AlfaParser) ParseFields(ctx context.Context, methodURL string) ([]model.Field, error) {
	if methodURL == "" {
		return nil, nil
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, methodURL, nil)
	if err != nil {
		return nil, err
	}
	p.setHeaders(req)

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

	doc.Find("div[class*='response'], table, div[class*='schema'], pre").Each(func(i int, s *goquery.Selection) {
		text := s.Text()
		lines := strings.Split(text, "\n")

		for _, line := range lines {
			line = strings.TrimSpace(line)
			if line == "" || strings.HasPrefix(line, "{") || strings.HasPrefix(line, "[") {
				continue
			}

			parts := strings.SplitN(line, ":", 2)
			if len(parts) == 2 {
				fieldName := strings.TrimSpace(parts[0])
				fieldName = strings.Trim(fieldName, `",{}`)

				if fieldName != "" && !strings.Contains(fieldName, " ") {
					description := strings.TrimSpace(parts[1])
					required := strings.Contains(description, "required") ||
						strings.Contains(description, "Обязательное") ||
						strings.Contains(description, "обязательно")

					fields = append(fields, model.Field{
						Name:        fieldName,
						Required:    required,
						Description: description,
					})
				}
			}
		}
	})

	return fields, nil
}
