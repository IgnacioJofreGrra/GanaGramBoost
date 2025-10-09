import json
import re
import unicodedata

from itertools import islice
from pathlib import Path
from time import perf_counter, sleep
from typing import Callable, Iterator, List, Optional, Set
from urllib.parse import urlparse

from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException  # type: ignore
from selenium.webdriver.common.by import By  # type: ignore
from selenium.webdriver.common.keys import Keys  # type: ignore
from selenium.webdriver.support import expected_conditions as EC  # type: ignore
from selenium.webdriver.support.wait import WebDriverWait  # type: ignore

from .browser import Browser
from .comments import Comments
from .implicitly_wait import ImplicitlyWait


class Bot(Browser):
    __version__ = '2.1.1'
    __author__ = 'IgnacioJofreGrra'

    def __init__(self, *args, **kwargs):
        self.url_base = 'https://www.instagram.com/'
        self.url_login = self.url_base + 'accounts/login'
        self.timeout = kwargs.get('timeout', 30)
        self.records_path = kwargs['records_path']
        self.connections: List[str] = []
        self.num_comments = 0
        self.comment_attempts = 0
        self.comment_successes = 0
        self.comment_failures = 0
        self.consecutive_failures = 0
        self.last_comment_error: Optional[str] = None
        self.comment_history_dir = Path(self.records_path) / 'history'

        super().__init__(*args, **kwargs)

        self.implicitly_wait = ImplicitlyWait(self.driver, self.timeout)
        self.implicitly_wait.enable()

    @staticmethod
    def _parse_counter_text(raw_text: Optional[str]) -> int:
        """Convierte el texto de conteo de Instagram en un entero.

        Maneja formatos como "3,208", "3.208", "2,9 mil", "1.2k", "1,3 millones", etc.
        """

        if not raw_text:
            raise ValueError('El texto de conteo está vacío.')

        text = unicodedata.normalize('NFKC', raw_text).strip().lower()
        text = re.sub(r'(seguidores|seguidos|followers|following|\+)', '', text)
        text = text.replace('\u202f', '').replace('\u200a', '').strip()

        # Detectar sufijos (mil, k, m, millones, etc.)
        multiplier = 1
        suffix_map = {
            'mil': 1_000,
            'k': 1_000,
            'm': 1_000_000,
            'millones': 1_000_000,
            'millón': 1_000_000,
            'millions': 1_000_000,
        }

        for suffix, factor in suffix_map.items():
            if suffix in text:
                multiplier = factor
                text = text.replace(suffix, '')

        text = text.replace(',', '.').replace(' ', '')

        if not text:
            raise ValueError(f'Formato de conteo no reconocido: "{raw_text}"')

        try:
            if multiplier != 1 and any(ch == '.' for ch in text):
                value = float(text)
            elif multiplier != 1 and any(ch.isdigit() for ch in text):
                value = float(text)
            elif '.' in text:
                # Si hay puntos, se asume separador de miles
                value = int(text.replace('.', ''))
                return value * multiplier
            else:
                value = float(text)
        except ValueError as exc:
            raise ValueError(f'No se puede convertir el conteo "{raw_text}".') from exc

        return int(round(value * multiplier))

    @staticmethod
    @staticmethod
    def _is_logged_in(driver) -> bool:
        """Retorna True si existe una sesión activa en Instagram."""

        try:
            cookie = driver.get_cookie('sessionid')
        except WebDriverException:
            return False

        return bool(cookie and cookie.get('value'))

    @staticmethod
    def _normalize_username(username: str) -> str:
        return username.lstrip('@').strip().lower()

    def _get_comment_history_path(self, post_url: str) -> Path:
        parsed = urlparse(post_url)
        slug = parsed.path.strip('/') or 'root'
        safe_slug = re.sub(r'[^a-z0-9_\-]+', '_', slug.lower())
        history_dir = self.comment_history_dir
        history_dir.mkdir(parents=True, exist_ok=True)
        return history_dir / f'{safe_slug}_commented.txt'

    def _append_comment_history(self, history_path: Path, users: List[str]) -> None:
        if not users:
            return

        history_path.parent.mkdir(parents=True, exist_ok=True)
        with history_path.open('a', encoding='utf8') as file:
            for user in users:
                file.write(f"{self._normalize_username(user)}\n")

    def _dismiss_login_popups(self) -> None:
        """Cierra modales posteriores al inicio de sesión (guardar info, notificaciones, etc.)."""

        modal_xpaths = [
            "//button[contains(., 'Guardar información') or contains(., 'Save info') or contains(., 'Save Info')]",
            "//button[contains(., 'Ahora no') or contains(., 'Not now') or contains(., 'Not Now')]",
            "//button[contains(., 'Cancelar') or contains(., 'Cancel')]",
        ]

        for xpath_expr in modal_xpaths:
            try:
                WebDriverWait(self.driver, 5).until(EC.element_to_be_clickable((By.XPATH, xpath_expr))).click()
            except KeyboardInterrupt:  # Permitir cancelar manualmente
                raise
            except (TimeoutException, NoSuchElementException, WebDriverException):
                continue
            except Exception:  # noqa: BLE001
                continue

    def log_in(self, username: str, password: str) -> None:
        """Inicia sesión en Instagram con las credenciales proporcionadas."""

        cookie_name = 'sessionid'
        self.connections.clear()

        self.driver.get(self.url_login)

        # Esperar a que el HTML esté cargado
        WebDriverWait(self.driver, self.timeout).until(
            lambda x: 'js-focus-visible' in x.find_element(By.TAG_NAME, 'html').get_attribute('class')
        )

        try:
            with self.implicitly_wait.ignore():
                self.driver.find_element(By.CSS_SELECTOR, 'div[role=dialog] button').click()
        except NoSuchElementException:
            pass  # El cuadro emergente no aparece para todos

        try:
            with open(f'cookies/{username}.json', 'r') as file:
                cookie = json.load(file)
        except FileNotFoundError:
            cookie = None

        if cookie:
            self.driver.add_cookie(cookie)
            self.driver.get(self.url_base)
            if self._is_logged_in(self.driver):
                return

        # Sin sesión previa o cookie inválida: intentar inicio de sesión manual
        self.driver.get(self.url_login)

        try:
            username_input = WebDriverWait(self.driver, self.timeout).until(
                EC.visibility_of_element_located((By.NAME, 'username'))
            )
            password_input = WebDriverWait(self.driver, self.timeout).until(
                EC.visibility_of_element_located((By.NAME, 'password'))
            )
        except TimeoutException as exc:
            raise TimeoutException('No se pudo ubicar el formulario de inicio de sesión en Instagram.') from exc

        username_input.clear()
        username_input.send_keys(username)
        password_input.clear()
        password_input.send_keys(password)
        password_input.send_keys(Keys.ENTER)

        try:
            WebDriverWait(self.driver, self.timeout * 2).until(lambda drv: self._is_logged_in(drv))
        except TimeoutException as exc:
            current_url = self.driver.current_url
            if 'two_factor' in current_url or 'challenge' in current_url:
                raise TimeoutException(
                    'Instagram está solicitando un desafío adicional (2FA, correo o similar). Completa el desafío manualmente y vuelve a ejecutar el bot.'
                ) from exc
            raise TimeoutException('No fue posible iniciar sesión en Instagram. Verifica tus credenciales o tu conexión.') from exc

        self._dismiss_login_popups()
        self.driver.get(self.url_base)

        cookie = self.driver.get_cookie(cookie_name)
        if cookie:
            Path('cookies/').mkdir(exist_ok=True)
            with open(f'cookies/{username}.json', 'w') as file:
                json.dump(cookie, file)

    def get_user_connections_from_records(
        self,
        username: Optional[str] = None,
        specific_file: Optional[str] = None,
        limit: Optional[int] = None,
        followers: bool = True,
    ) -> bool:
        """Obtiene seguidores o seguidos desde los registros locales."""

        try:
            with open(specific_file or f'{self.records_path}//{username}.txt', 'r') as file:
                source = islice(file, limit) if limit else file.readlines()
                self.connections = [line.rstrip('\n').strip().lower() for line in source if line.strip()]
        except FileNotFoundError:
            return False

        if (self.connections and not limit) or (limit and len(self.connections) == limit):
            return True

        return False

    def save_connections(self, username: str, connections_ext: List[str]) -> None:
        """Guarda usuarios adicionales en el archivo correspondiente al objetivo."""

        Path(self.records_path).mkdir(parents=True, exist_ok=True)
        with open(f'{self.records_path}//{username}.txt', 'a') as file:
            file.writelines(f'{line}\n' for line in connections_ext)

    def get_user_connections_from_web(
        self,
        limit: Optional[int] = None,
        followers: bool = True,
        force_search: bool = False,
    ) -> None:
        """Busca seguidores o seguidos del usuario objetivo directamente en Instagram."""

        selector = 'ul li a span' if followers else 'ul li:nth-child(3) a span'
        connections_link = self.driver.find_element(By.CSS_SELECTOR, selector)

        limit_text = connections_link.get_attribute('title') or connections_link.text

        try:
            connections_limit = self._parse_counter_text(limit_text)
        except ValueError as exc:
            exit(
                'No se puede interpretar el número de seguidores/seguidos del usuario objetivo. '
                f'Instagram devolvió: "{limit_text}". '
                'Verifica manualmente el perfil para confirmar el total o intenta deshabilitar Force Search.'
            )

        if not force_search and self.connections and (not limit or connections_limit < limit):
            return

        connections_link.click()

        WebDriverWait(self.driver, self.timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'div[role=dialog] > div > div:nth-of-type(2)'))
        )

        try:
            debug_dialog = self.driver.execute_script(
                """
                const dialog = document.querySelector("div[role='dialog']");
                const scrollCandidates = dialog ? Array.from(dialog.querySelectorAll('*'))
                    .filter(el => el.className && el.className.toString().includes('_aano'))
                    .map(el => el.className).slice(0, 5) : [];
                return {
                    hasDialog: !!dialog,
                    sampleHtml: dialog ? dialog.outerHTML.slice(0, 1000) : null,
                    classCandidates: scrollCandidates,
                    dialogCount: document.querySelectorAll("div[role='dialog']").length
                };
                """
            )
            print(f"Debug diálogo Instagram: {debug_dialog}")
        except Exception as exc:  # noqa: BLE001
            print(f"No se pudo obtener depuración del diálogo: {exc}")

        try:
            container_info = self.driver.execute_script(
                """
                const dialog = document.querySelector("div[role='dialog']");
                if (!dialog) {
                    window._igConnectionsContainer = null;
                    return { hasDialog: false };
                }

                const candidates = Array.from(dialog.querySelectorAll('[style*="overflow"], [style*="scroll"], div'));
                const scrollable = candidates.find(el => {
                    const style = window.getComputedStyle(el);
                    return style.overflowY === 'auto' || style.overflowY === 'scroll';
                }) || dialog.querySelector("div[class*='_aano']") || dialog.querySelector("div[class*='_ab8w']");

                window._igConnectionsContainer = scrollable || dialog;

                return {
                    hasDialog: true,
                    containerTag: scrollable ? scrollable.tagName : null,
                    containerClass: scrollable ? scrollable.className : null
                };
                """
            )
            print(f"Contenedor desplazable Instagram: {container_info}")
        except Exception as exc:  # noqa: BLE001
            print(f"No se pudo identificar el contenedor desplazable: {exc}")

        try:
            first_entry = WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div[role='dialog'] ul li"))
            )
            self.driver.execute_script('arguments[0].scrollIntoView(true);', first_entry)
        except (TimeoutException, NoSuchElementException):
            pass
        except Exception:  # noqa: BLE001
            pass

        timestamp = perf_counter()
        max_to_fetch = min(limit, connections_limit) if limit else connections_limit
        remaining = max(max_to_fetch - len(self.connections), 0)

        connections_set = {conn.lower() for conn in self.connections}
        connections_added_count = 0
        total_connections_searched = 0

        blocked_prefixes = {
            'accounts',
            'explore',
            'direct',
            'p',
            'stories',
            'reels',
            'tv',
            'challenge',
            'channel',
            'ads',
            'about',
            'support',
        }

        js_get_usernames = """
            const dialog = document.querySelector("div[role='dialog']");
            if (!dialog) { return []; }

            const container = window._igConnectionsContainer
                || dialog.querySelector("div[class*='_aano']")
                || dialog.querySelector('[style*="overflow"], [style*="scroll"]')
                || dialog;

            const anchors = Array.from(container.querySelectorAll("a[href]"));
            const usernames = [];
            const seen = new Set();

            for (const anchor of anchors) {
                let href = anchor.getAttribute('href') || '';
                if (!href) { continue; }

                if (href.startsWith('https://www.instagram.com/')) {
                    href = href.substring('https://www.instagram.com/'.length);
                }

                if (!href.startsWith('/')) { continue; }

                href = href.replace(/^\/+/, '').split('?')[0];
                const username = href.split('/')[0].trim();

                if (!username || username === 'accounts' || username === 'login') { continue; }
                if (!/^[a-z0-9._]+$/i.test(username)) { continue; }

                const lower = username.toLowerCase();
                if (seen.has(lower)) { continue; }

                seen.add(lower);
                usernames.push(username);
            }

            return usernames;
        """

        idle_cycles = 0
        max_idle_cycles = 80

        while perf_counter() - timestamp < self.timeout:
            raw_usernames = self.driver.execute_script(js_get_usernames)

            if not isinstance(raw_usernames, list):
                raw_usernames = []

            diff_connections_count = len(raw_usernames) - total_connections_searched
            print(f'Se detectaron {len(raw_usernames)} usuarios visibles en el modal (nuevos: {max(diff_connections_count, 0)}).')

            if diff_connections_count > 0:
                idle_cycles = 0
                total_connections_searched = len(raw_usernames)
                timestamp = perf_counter()

                for username in raw_usernames[-diff_connections_count:]:
                    normalized_username = username.lstrip('@').lower()

                    if normalized_username in blocked_prefixes:
                        continue

                    connection_username = '@' + normalized_username

                    if connection_username not in connections_set:
                        self.connections.append(connection_username)
                        connections_set.add(connection_username)
                        connections_added_count += 1

                        if not force_search and remaining > 0:
                            remaining -= 1
                            if remaining == 0:
                                return

                if total_connections_searched >= connections_limit:
                    break
            else:
                idle_cycles += 1

            try:
                scroll_info = self.driver.execute_script(
                    """
                    const container = window._igConnectionsContainer
                        || document.querySelector("div[role='dialog'] div[role='dialog']")
                        || document.querySelector("div[role='dialog'] div:nth-of-type(2)");

                    if (!container) {
                        return { scrolled: false };
                    }

                    const beforeTop = container.scrollTop;
                    const beforeHeight = container.scrollHeight;

                    const target = Math.min(
                        beforeTop + container.clientHeight * 0.9,
                        container.scrollHeight
                    );

                    container.scrollTop = target;

                    const afterTop = container.scrollTop;
                    const afterHeight = container.scrollHeight;
                    const reachedBottom = (afterTop + container.clientHeight) >= afterHeight - 2;

                    return {
                        scrolled: afterTop !== beforeTop,
                        reachedBottom,
                        beforeTop,
                        afterTop,
                        beforeHeight,
                        afterHeight
                    };
                    """
                )
            except Exception:
                scroll_info = None

            if diff_connections_count <= 0:
                wait_time = min(2.0, 0.5 + idle_cycles * 0.1)
                sleep(wait_time)

            if idle_cycles >= max_idle_cycles:
                print('No se detectaron nuevos usuarios tras múltiples desplazamientos del modal.')
                break

    def get_user_from_post(self, url: str) -> str:
        """Encuentra el dueño de la publicación indicada."""

        self.driver.get(url)

        # Intentar varias estrategias para encontrar el usuario dueño del post
        def extract_from_href(href: str) -> Optional[str]:
            try:
                if href.startswith('https://www.instagram.com/'):
                    path = href.replace('https://www.instagram.com/', '')
                elif href.startswith('/'):
                    path = href[1:]
                else:
                    return None
                parts = [p for p in path.split('/') if p]
                if parts:
                    return parts[0]
            except Exception:
                return None
            return None

        # 1) Buscar enlaces en el encabezado del artículo
        selectors = [
            "article header a[href^='https://www.instagram.com/']",
            "header a[href^='https://www.instagram.com/']",
            "article header a[href^='/']",
            "header a[href^='/']",
        ]

        for sel in selectors:
            try:
                anchors = self.driver.find_elements(By.CSS_SELECTOR, sel)
                if anchors:
                    for a in anchors:
                        href = a.get_attribute('href')
                        username = extract_from_href(href) if href else None
                        if username:
                            return username
            except Exception:
                continue

        # 2) Respaldo: parsear JSON-LD en la página para extraer el autor
        try:
            scripts = self.driver.find_elements(By.CSS_SELECTOR, "script[type='application/ld+json']")
            for s in scripts:
                try:
                    data = json.loads(s.get_attribute('innerText'))
                    # data puede ser dict o lista
                    items = data if isinstance(data, list) else [data]
                    for item in items:
                        author = item.get('author')
                        if isinstance(author, dict):
                            username = author.get('alternateName') or author.get('name')
                            if isinstance(username, str) and username:
                                return username.strip('@')
                except Exception:
                    continue
        except Exception:
            pass

        raise NoSuchElementException(
            'No se pudo detectar automáticamente el dueño del post. Configura "User Target" en config.ini dentro de [Optional].'
        )

    def _find_comment_input(self, wait: bool = True):
        """Localiza el campo editable del cuadro de comentarios."""

        selectors = [
            "article[role='presentation'] form textarea",
            "article form textarea",
            "form textarea",
        ]

        for selector in selectors:
            if wait:
                try:
                    return WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                    )
                except TimeoutException:
                    continue
            else:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                if elements:
                    return elements[0]

        # Respaldo: Instagram puede renderizar un div contenteditable en lugar del textarea.
        if wait:
            try:
                return WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div[role='textbox'][contenteditable='true']"))
                )
            except TimeoutException as exc:
                raise NoSuchElementException('No se encontró el campo de comentario en la publicación.') from exc

        elements = self.driver.find_elements(By.CSS_SELECTOR, "div[role='textbox'][contenteditable='true']")
        if elements:
            return elements[0]

        return None

    def _get_comment_input_value(self) -> str:
        """Devuelve el contenido actual del cuadro de comentarios."""

        with self.implicitly_wait.ignore():
            element = self._find_comment_input(wait=False)

        if not element:
            return ''

        if element.tag_name.lower() == 'textarea':
            return (element.get_attribute('value') or '').strip()

        text = element.text or element.get_attribute('innerText') or ''
        return text.strip()

    def _find_comment_submit(self):
        """Localiza el control que envía el comentario."""

        with self.implicitly_wait.ignore():
            form_element = None
            try:
                input_element = self._find_comment_input(wait=False)
                if input_element:
                    form_element = input_element.find_element(By.XPATH, "ancestor::form[1]")
            except NoSuchElementException:
                form_element = None

        js_locator = """
            const form = arguments[0] || document;
            const preferredLabels = ['post', 'publicar', 'share', 'send', 'enviar'];

            const candidates = Array.from(
                form.querySelectorAll("button, div[role='button'], span[role='button']")
            );

            const isSubmit = (el) => {
                if (!el || !el.isConnected) return false;
                const tag = el.tagName.toLowerCase();
                const role = (el.getAttribute('role') || '').toLowerCase();
                const ariaDisabled = (el.getAttribute('aria-disabled') || '').toLowerCase();
                if (ariaDisabled === 'true') return false;
                if (el.disabled) return false;

                const ariaLabel = (el.getAttribute('aria-label') || '').trim().toLowerCase();
                if (ariaLabel.includes('emoji') || ariaLabel.includes('smile')) {
                    return false;
                }

                const dataTestId = (el.getAttribute('data-testid') || '').toLowerCase();
                if (dataTestId.includes('emoji')) return false;

                const text = (el.innerText || el.textContent || '').trim().toLowerCase();

                if (tag === 'button' && el.getAttribute('type') === 'submit') return true;
                if (tag === 'button' && text && preferredLabels.includes(text)) return true;
                if (role === 'button' && text && preferredLabels.includes(text)) return true;

                if (!text && ariaLabel && preferredLabels.includes(ariaLabel)) return true;

                if (text && text.length <= 2) return false;
                if (tag === 'button' && !ariaLabel && !text && el.querySelector('svg')) return false;

                return false;
            };

            return candidates.find(isSubmit) || null;
        """

        try:
            submit_candidate = self.driver.execute_script(js_locator, form_element)
            if submit_candidate:
                return submit_candidate
        except Exception:  # noqa: BLE001
            pass

        selectors = [
            "article[role='presentation'] form button[type='submit']",
            "article form button[type='submit']",
            "form button[type='submit']",
            "article[role='presentation'] form button:not([disabled])",
            "form button:not([disabled])",
            "article[role='presentation'] form div[role='button']",
            "form div[role='button']",
        ]

        skip_keywords = ['emoji', 'smile', 'gif']

        for selector in selectors:
            try:
                button = WebDriverWait(self.driver, 2).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                )
                if not button:
                    continue

                attributes = ' '.join(
                    (button.get_attribute(attr) or '').lower() for attr in ['aria-label', 'data-testid']
                )
                if any(keyword in attributes for keyword in skip_keywords):
                    continue

                text = (button.text or '').strip().lower()
                if not text and button.tag_name.lower() == 'button' and button.get_attribute('type') != 'submit':
                    maybe_svg = button.find_elements(By.TAG_NAME, 'svg')
                    if maybe_svg:
                        continue

                if button.is_displayed() and button.is_enabled():
                    return button
            except TimeoutException:
                continue

        texts = ['publicar', 'post', 'share', 'send', 'enviar']
        for text in texts:
            try:
                button = WebDriverWait(self.driver, 2).until(
                    EC.element_to_be_clickable((By.XPATH, f"//button[translate(normalize-space(text()), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')='{text}']"))
                )
                if button and button.is_displayed() and button.is_enabled():
                    return button
            except TimeoutException:
                continue

        return None

    def _set_comment_value_js(self, element, comment: str) -> None:
        """Escribe el comentario mediante JavaScript garantizando los eventos necesarios."""

        self.driver.execute_script(
            """
            const el = arguments[0];
            const value = arguments[1];

            if (!el) { return; }

            el.focus();

            const tag = el.tagName.toLowerCase();

            if (tag === 'textarea') {
                el.value = '';
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.value = value;
            } else {
                el.innerHTML = '';
                el.textContent = value;
            }

            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        """,
            element,
            comment,
        )

    def _record_comment_attempt(
        self,
        success: bool,
        comment: str,
        duration: float,
        error: Optional[str] = None,
        users: Optional[List[str]] = None,
    ) -> None:
        """Actualiza métricas y reporta el estado de cada intento de envío."""

        snippet = comment.strip()
        if len(snippet) > 80:
            snippet = snippet[:77] + '…'

        self.comment_attempts += 1

        users_info = ''
        if users:
            users_info = ' | Usuarios: ' + ', '.join(users)

        if success:
            self.comment_successes += 1
            self.consecutive_failures = 0
            self.last_comment_error = None
            print(
                f"Comentario #{self.comment_successes} publicado en {duration:.2f}s. "
                f"Totales: {self.comment_successes}/{self.comment_attempts} (fallos: {self.comment_failures}). "
                f"Contenido: {snippet}{users_info}"
            )
        else:
            self.comment_failures += 1
            self.consecutive_failures += 1
            self.last_comment_error = error
            print(
                f"Fallo al enviar comentario (intento {self.comment_attempts}). "
                f"Consecutivos fallidos: {self.consecutive_failures}. "
                f"Duración: {duration:.2f}s. Motivo: {error or 'No se vació el campo de comentario.'}{users_info}"
            )

    def write_comment(self, comment: str) -> None:
        """Escribe el comentario en el cuadro de texto de la publicación."""

        input_element = self._find_comment_input()

        try:
            WebDriverWait(self.driver, self.timeout).until(EC.element_to_be_clickable(input_element)).click()
        except Exception:  # noqa: BLE001
            self.driver.execute_script('arguments[0].focus();', input_element)

        try:
            if input_element.tag_name.lower() == 'textarea':
                input_element.clear()
                input_element.send_keys(comment)
            else:
                input_element.send_keys(Keys.CONTROL, 'a')
                input_element.send_keys(Keys.DELETE)
                input_element.send_keys(comment)
        except WebDriverException:
            self._set_comment_value_js(input_element, comment)
        else:
            self.driver.execute_script(
                "arguments[0].dispatchEvent(new Event('input', { bubbles: true }));",
                input_element,
            )
            return

        self.driver.execute_script(
            "arguments[0].dispatchEvent(new Event('input', { bubbles: true }));",
            input_element,
        )
        self.driver.execute_script(
            "arguments[0].dispatchEvent(new Event('change', { bubbles: true }));",
            input_element,
        )

    def override_post_requests_js(self, comment: str) -> None:
        """Sobrescribe temporalmente las peticiones POST para permitir caracteres especiales."""

        payload = json.dumps(comment)
        self.driver.execute_script(
            '''
            XMLHttpRequest.prototype.realSend = XMLHttpRequest.prototype.send;
            const re = /comment_text=.*&replied_to_comment_id=/;

            XMLHttpRequest.prototype.send = function(data) {
                if (re.test(data)) {
                    data = 'comment_text=' + encodeURIComponent(%s) + '&replied_to_comment_id=';
                }
                this.realSend(data);
            };
            '''
            % payload
        )

    def send_comment(self) -> bool:
        """Pulsa el botón de publicación y espera a que Instagram procese el comentario."""

        try:
            submit_button = self._find_comment_submit()

            if submit_button:
                try:
                    submit_button.click()
                except WebDriverException:
                    self.driver.execute_script('arguments[0].click();', submit_button)
            else:
                input_element = self._find_comment_input(wait=False)
                if input_element:
                    input_element.send_keys(Keys.ENTER)
                else:
                    raise NoSuchElementException('No se encontró el botón para publicar el comentario.')
        except WebDriverException:
            input_element = self._find_comment_input(wait=False)
            if input_element:
                input_element.send_keys(Keys.ENTER)
            else:
                sleep(2)
                raise

        with self.implicitly_wait.ignore():
            WebDriverWait(self.driver, self.timeout).until_not(
                EC.presence_of_element_located((By.CSS_SELECTOR, "article[role='presentation'] form > div[data-visualcompletion='loading-state']"))
            )

        try:
            WebDriverWait(self.driver, self.timeout).until(lambda _: not self._get_comment_input_value())
        except TimeoutException:
            return False

        return True

    def comment_post(self, url: str, expr: str, get_interval: Callable[[], float]) -> None:
        """Genera comentarios según la expresión y los envía a la publicación."""

        expr_parts = [fragment.replace('\@', '@') for fragment in re.split(r'(?<!\\)@', expr)]
        mentions_per_comment = len(expr_parts) - 1

        if self.driver.current_url != url:
            self.driver.get(url)

        if mentions_per_comment <= 0:
            raise ValueError('La expresión debe incluir al menos una mención @ para generar comentarios automáticos.')

        history_path = self._get_comment_history_path(url)
        already_tagged: Set[str] = set()

        if history_path.exists():
            try:
                with history_path.open('r', encoding='utf8') as file:
                    already_tagged = {line.strip().lower() for line in file if line.strip()}
            except Exception:  # noqa: BLE001
                already_tagged = set()

        unique_connections: List[str] = []
        seen: Set[str] = set(already_tagged)

        for username in self.connections:
            normalized = self._normalize_username(username)
            if not normalized or normalized in seen:
                continue

            seen.add(normalized)
            unique_connections.append('@' + normalized)

        filtered_out = len(self.connections) - len(unique_connections)
        if filtered_out:
            print(f'Se omitirán {filtered_out} cuentas ya etiquetadas anteriormente en esta publicación.')

        self.connections = unique_connections

        def chunk_connections() -> Iterator[List[str]]:
            total = len(self.connections)
            step = mentions_per_comment
            for idx in range(0, (total // step) * step, step):
                yield self.connections[idx: idx + step]

        comments = Comments(chunk_connections(), expr_parts)

        for original_comment, users in comments.generate():
            success = False
            has_input = False

            while not success:
                if not has_input:
                    try:
                        self.write_comment(original_comment)
                    except WebDriverException:
                        self._set_comment_value_js(self._find_comment_input(), original_comment)
                    has_input = True

                attempt_started = perf_counter()

                try:
                    success = self.send_comment()
                except Exception as exc:  # noqa: BLE001
                    duration = perf_counter() - attempt_started
                    self._record_comment_attempt(False, original_comment, duration, str(exc), users)
                    raise

                duration = perf_counter() - attempt_started

                if success:
                    self._record_comment_attempt(True, original_comment, duration, users=users)
                    normalized_users = [self._normalize_username(user) for user in users]
                    already_tagged.update(normalized_users)
                    self._append_comment_history(history_path, users)
                    self.num_comments += 1
                    sleep(get_interval())
                else:
                    self._record_comment_attempt(False, original_comment, duration, users=users)
                    has_input = bool(self._get_comment_input_value())
                    if not has_input:
                        sleep(1)
                    continue

    def quit(self, message: Optional[str] = None) -> None:
        """Cierra el navegador y finaliza la ejecución con un mensaje opcional."""

        self.driver.quit()
        exit(message)

