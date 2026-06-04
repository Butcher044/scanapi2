package parser

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"strings"

	"github.com/PuerkitoBio/goquery"
	"system-monitoring/internal/model"
)

// SberParser парсер для Сбера
type SberParser struct {
	client  *http.Client
	BaseURL string
}

func NewSberParser() *SberParser {
	return &SberParser{
		client:  &http.Client{},
		BaseURL: "https://developers.sber.ru",
	}
}

func (p *SberParser) Name() string {
	return "sber"
}

// Сервисы Сбера - захардкожено
func (p *SberParser) ParseServices(ctx context.Context) ([]model.Service, error) {
	return []model.Service{
		{Name: "GigaChat API", URL: "https://developers.sber.ru/docs/ru/gigachat/api/main"},
		{Name: "Sber API", URL: "https://developers.sber.ru/docs/ru/sber-api/specifications/overview"},
		{Name: "SaluteSpeech API", URL: "https://developers.sber.ru/docs/ru/salutespeech/api/main"},
	}, nil
}

func (p *SberParser) ParseMethods(ctx context.Context, serviceURL string) ([]model.Method, error) {
	log.Printf("[Sber] Парсинг методов для: %s", serviceURL)

	// Пробуем найти OpenAPI spec
	specURL, err := FindOpenAPISpecURL(ctx, p.client, serviceURL)
	if err != nil {
		log.Printf("[Sber] Ошибка при поиске spec (не критично): %v", err)
		// Продолжаем без ошибки
	}

	log.Printf("[Sber] spec URL: %s", specURL)

	// Если нашли OpenAPI spec - пробуем распарсить
	if specURL != "" {
		methods, _, err := ParseOpenAPISpec(ctx, p.client, specURL)
		if err == nil && len(methods) > 0 {
			log.Printf("[Sber] Найдено методов из OpenAPI: %d", len(methods))
			return methods, nil
		}
		log.Printf("[Sber] Не удалось распарсить OpenAPI или методов 0: %v", err)
	}

	// HTML парсинг
	log.Printf("[Sber] Пробуем HTML парсинг")
	return p.parseMethodsHTML(ctx, serviceURL)
}

// parseMethodsHTML парсит методы из боковой навигации
func (p *SberParser) parseMethodsHTML(ctx context.Context, serviceURL string) ([]model.Method, error) {
	log.Printf("[Sber] Запрашиваем URL: %s", serviceURL)

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, serviceURL, nil)
	if err != nil {
		log.Printf("[Sber] Ошибка создания запроса: %v", err)
		return nil, err
	}
	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

	resp, err := p.client.Do(req)
	if err != nil {
		log.Printf("[Sber] Ошибка запроса: %v", err)
		return nil, err
	}
	defer resp.Body.Close()

	log.Printf("[Sber] Статус: %d", resp.StatusCode)

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("failed to fetch %s: %d", serviceURL, resp.StatusCode)
	}

	doc, err := goquery.NewDocumentFromReader(resp.Body)
	if err != nil {
		log.Printf("[Sber] Ошибка парсинга HTML: %v", err)
		return nil, err
	}

	// Отладка
	allLinks := doc.Find("a[href]")
	log.Printf("[Sber] Всего ссылок на странице: %d", allLinks.Length())

	// Выводим первые 20 href для отладки
	hrefs := make(map[string]bool)
	doc.Find("a[href]").Each(func(i int, s *goquery.Selection) {
		href, _ := s.Attr("href")
		if href != "" && !hrefs[href] {
			hrefs[href] = true
		}
	})
	log.Printf("[Sber] Уникальных href: %d", len(hrefs))
	count := 0
	for href := range hrefs {
		log.Printf("[Sber]   href: %s", href)
		count++
		if count >= 20 {
			log.Printf("[Sber]   ... (еще %d ссылок)", len(hrefs)-count)
			break
		}
	}

	var methods []model.Method
	seen := make(map[string]bool)

	// Сначала ищем элементы с классом api-method (для GigaChat и других API Сбера)
	// Класс содержит api-method post или api-method get
	doc.Find("li.api-method a[href]").Each(func(i int, s *goquery.Selection) {
		href, _ := s.Attr("href")
		text := strings.TrimSpace(s.Text())

		if text == "" || len(text) < 3 {
			return
		}

		// Пропускаем нерелевантные
		lowerHref := strings.ToLower(href)
		lowerText := strings.ToLower(text)
		if strings.Contains(lowerHref, "/connection") || strings.Contains(lowerHref, "/connecting") ||
			strings.Contains(lowerHref, "/how-to") || strings.Contains(lowerHref, "/tutorial") ||
			strings.Contains(lowerText, "подключение") || strings.Contains(lowerText, "начало") ||
			strings.Contains(lowerText, "введение") {
			return
		}

		// Определяем HTTP метод из класса родительского li
		httpMethod := "GET"
		li := s.Closest("li")
		if li != nil {
			liClass, _ := li.Attr("class")
			if strings.Contains(liClass, "post") {
				httpMethod = "POST"
			} else if strings.Contains(liClass, "get") {
				httpMethod = "GET"
			} else if strings.Contains(liClass, "put") {
				httpMethod = "PUT"
			} else if strings.Contains(liClass, "delete") {
				httpMethod = "DELETE"
			}
		}

		// Пропускаем дубликаты
		key := httpMethod + ":" + text
		if seen[key] {
			return
		}
		seen[key] = true

		url := href
		if !strings.HasPrefix(href, "http") {
			url = p.BaseURL + href
		}

		log.Printf("[Sber] Найден метод: %s %s", httpMethod, text)

		methods = append(methods, model.Method{
			Name:       text,
			HTTPMethod: httpMethod,
			URL:        url,
		})
	})

	// Если не нашли через li.api-method, пробуем общий парсинг всех ссылок в sidebar
	// Включая вложенные списки (ul внутри li)
	if len(methods) == 0 {
		log.Printf("[Sber] Не найдено через li.api-method, пробуем общий парсинг")

		// Ищем все ссылки в sidebar, включая вложенные
		doc.Find("nav a[href], aside a[href], div[class*='sidebar'] a[href], div[class*='menu'] a[href], ul[class*='menu'] a[href]").Each(func(i int, s *goquery.Selection) {
			href, _ := s.Attr("href")
			text := strings.TrimSpace(s.Text())

			if text == "" || len(text) < 3 {
				return
			}

			lowerHref := strings.ToLower(href)
			lowerText := strings.ToLower(text)

			// Пропускаем нерелевантные ссылки
			if strings.Contains(lowerHref, "/connection") || strings.Contains(lowerHref, "/connecting") ||
				strings.Contains(lowerHref, "/how-to") || strings.Contains(lowerHref, "/tutorial") ||
				strings.Contains(lowerHref, "/getting") || strings.Contains(lowerText, "подключение") ||
				strings.Contains(lowerText, "начало") || strings.Contains(lowerText, "введение") ||
				strings.Contains(lowerText, "сделк") || strings.Contains(lowerText, "справка") ||
				strings.Contains(lowerText, "rest api") || strings.Contains(lowerText, "руководство") ||
				strings.Contains(lowerText, "описание") || strings.Contains(lowerText, "версия") {
				return
			}

			// Пропускаем ссылки не на методы (например, ссылки на категории разделов)
			// Обычно методы имеют путь содержащий что-то вроде /api/ или /methods/
			// Но для Сбера это может быть просто текст на русском
			// Оставляем только если есть явные признаки метода
			isMethod := false
			if strings.Contains(lowerText, "создать") || strings.Contains(lowerText, "добавить") ||
				strings.Contains(lowerText, "получить") || strings.Contains(lowerText, "удалить") ||
				strings.Contains(lowerText, "обновить") || strings.Contains(lowerText, "изменить") ||
				strings.Contains(lowerText, "отправить") || strings.Contains(lowerText, "запрос") ||
				strings.Contains(lowerText, "список") || strings.Contains(lowerText, "проверить") ||
				strings.Contains(lowerText, "вызвать") || strings.Contains(lowerText, "выполнить") ||
				strings.Contains(lowerText, "generate") || strings.Contains(lowerText, "recognize") ||
				strings.Contains(lowerText, "send") || strings.Contains(lowerText, "get") ||
				strings.Contains(lowerText, "create") || strings.Contains(lowerText, "delete") ||
				strings.Contains(lowerText, "update") || strings.Contains(lowerText, "post") ||
				strings.Contains(lowerText, "put") || strings.Contains(lowerText, "patch") {
				isMethod = true
			}

			// Также проверяем URL на признаки метода
			if !isMethod && len(href) > 5 {
				// Если URL содержит явно метод (например, /api/v1/...), считаем методом
				if strings.Contains(lowerHref, "/api/") || strings.Contains(lowerHref, "/methods/") ||
					strings.Contains(lowerHref, "/endpoints/") || strings.Contains(lowerHref, "operation") {
					isMethod = true
				}
			}

			if !isMethod {
				return
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

			// Определяем HTTP метод
			httpMethod := ""
			lowerUrl := strings.ToLower(url)
			if strings.Contains(lowerUrl, "create") || strings.Contains(lowerText, "создать") ||
				strings.Contains(lowerText, "добавить") || strings.Contains(lowerText, "отправить") ||
				strings.Contains(lowerText, "generate") || strings.Contains(lowerText, "send") ||
				strings.Contains(lowerText, "post") {
				httpMethod = "POST"
			} else if strings.Contains(lowerUrl, "delete") || strings.Contains(lowerText, "удалить") {
				httpMethod = "DELETE"
			} else if strings.Contains(lowerUrl, "update") || strings.Contains(lowerText, "обновить") ||
				strings.Contains(lowerText, "изменить") || strings.Contains(lowerText, "patch") ||
				strings.Contains(lowerText, "put") {
				httpMethod = "PUT"
			} else if strings.Contains(lowerUrl, "get") || strings.Contains(lowerText, "получить") ||
				strings.Contains(lowerText, "список") || strings.Contains(lowerText, "запрос") ||
				strings.Contains(lowerText, "проверить") || strings.Contains(lowerText, "recognize") {
				httpMethod = "GET"
			}

			log.Printf("[Sber] Найден метод: %s %s", httpMethod, text)

			methods = append(methods, model.Method{
				Name:       text,
				HTTPMethod: httpMethod,
				URL:        url,
			})
		})
	}

	// Fallback: пробуем по всем ссылкам
	if len(methods) == 0 {
		doc.Find("a[href]").Each(func(i int, s *goquery.Selection) {
			href, _ := s.Attr("href")
			text := strings.TrimSpace(s.Text())

			if text == "" || len(text) < 3 {
				return
			}

			lowerHref := strings.ToLower(href)
			if strings.Contains(lowerHref, "/connection") || strings.Contains(lowerHref, "/connecting") ||
				strings.Contains(lowerHref, "/how-to") || strings.Contains(lowerHref, "/tutorial") {
				return
			}

			if seen[text] {
				return
			}
			seen[text] = true

			url := href
			if !strings.HasPrefix(href, "http") {
				url = p.BaseURL + href
			}

			methods = append(methods, model.Method{
				Name: text,
				URL:  url,
			})
		})
	}

	// Минимальный fallback
	if len(methods) == 0 {
		log.Printf("[Sber] WARNING: Fallback - методы не найдены!")
		methods = []model.Method{
			{Name: "FALLBACK_METHOD", URL: serviceURL},
		}
	}

	log.Printf("[Sber] Найдено методов: %d", len(methods))

	return methods, nil
}

func (p *SberParser) ParseFields(ctx context.Context, methodURL string) ([]model.Field, error) {
	if methodURL == "" {
		return nil, nil
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, methodURL, nil)
	if err != nil {
		return nil, err
	}

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

	// Ищем секцию с ответами
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