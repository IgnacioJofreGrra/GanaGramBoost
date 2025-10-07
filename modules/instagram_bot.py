import json
import re

from itertools import islice
from pathlib import Path
from time import perf_counter, sleep
from typing import Callable, Iterator, List, Optional

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

        super().__init__(*args, **kwargs)

        self.implicitly_wait = ImplicitlyWait(self.driver, self.timeout)
        self.implicitly_wait.enable()

    def log_in(self, username: str, password: str) -> None:
        """Inicia sesión en Instagram con las credenciales proporcionadas."""

        cookie_name = 'sessionid'

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
            WebDriverWait(self.driver, self.timeout).until(
                lambda driver: driver.get_log('browser')
            )
            self.driver.refresh()

        if 'not-logged-in' in self.driver.find_element(By.TAG_NAME, 'html').get_attribute('class'):
            username_input, password_input, *_ = self.driver.find_elements(By.CSS_SELECTOR, 'form input')
            username_input.send_keys(username)
            password_input.send_keys(password + Keys.ENTER)

            WebDriverWait(self.driver, self.timeout).until(
                lambda x: 'js logged-in' in x.find_element(By.TAG_NAME, 'html').get_attribute('class')
            )

            cookie = self.driver.get_cookie(cookie_name)
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
                self.connections = [line.rstrip('\n') for line in source]
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

        try:
            limit_text = connections_link.get_attribute('title') if followers else connections_link.text
            connections_limit = int(limit_text.replace(',', '').replace('.', '').replace(' ', ''))
        except ValueError:
            exit(
                'Debes elegir un usuario objetivo con menos de 10.000 seguidos. '
                'Instagram no muestra el número exacto si son demasiados y resulta complejo contemplar todos los formatos.'
            )

        if not force_search and self.connections and (not limit or connections_limit < limit):
            return

        connections_link.click()

        WebDriverWait(self.driver, self.timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'div[role=dialog] > div > div:nth-of-type(2)'))
        )

        self.driver.execute_script(
            "window._igConnectionsContainer = document.querySelector('div[role=dialog] > div > div:nth-of-type(2)');"
        )

        self.driver.find_element(By.CSS_SELECTOR, 'div[role=dialog] li > div > div:nth-of-type(2) > div:nth-of-type(2)').click()

        timestamp = perf_counter()
        max_to_fetch = min(limit, connections_limit) if limit else connections_limit
        remaining = max(max_to_fetch - len(self.connections), 0)

        connections_set = set(self.connections)
        connections_added_count = 0
        total_connections_searched = 0

        while perf_counter() - timestamp < self.timeout:
            connections_list = self.driver.find_elements(By.CSS_SELECTOR, 'div[role=dialog] ul li span a')
            diff_connections_count = len(connections_list) - total_connections_searched

            if diff_connections_count > 0:
                total_connections_searched += diff_connections_count
                timestamp = perf_counter()

                for connection in connections_list[-diff_connections_count:]:
                    connection_username = '@' + connection.text
                    if connection_username and connection_username not in connections_set:
                        self.connections.append(connection_username)
                        connections_set.add(connection_username)
                        connections_added_count += 1

                        if not force_search and remaining > 0:
                            remaining -= 1
                            if remaining == 0:
                                return

                if total_connections_searched >= connections_limit:
                    break

            self.driver.execute_script(
                'window._igConnectionsContainer.scrollTo(0, window._igConnectionsContainer.scrollHeight);'
            )

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

    def write_comment(self, comment: str) -> None:
        """Escribe el comentario en el cuadro de texto de la publicación."""

        textarea_selector = "article[role='presentation'] form > textarea"
        self.driver.find_element(By.CSS_SELECTOR, textarea_selector).click()
        self.driver.find_element(By.CSS_SELECTOR, textarea_selector).send_keys(comment)

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
            self.driver.find_element(By.CSS_SELECTOR, "article[role='presentation'] form > button:nth-of-type(2)").click()
        except WebDriverException:
            sleep(60)

        with self.implicitly_wait.ignore():
            WebDriverWait(self.driver, self.timeout).until_not(
                EC.presence_of_element_located((By.CSS_SELECTOR, "article[role='presentation'] form > div[data-visualcompletion='loading-state']"))
            )

        try:
            WebDriverWait(self.driver, self.timeout).until_not(
                lambda driver: driver.find_element(By.CSS_SELECTOR, "article[role='presentation'] form > textarea").text
            )
        except TimeoutException:
            return False

        return True

    def comment_post(self, url: str, expr: str, get_interval: Callable[[], float]) -> None:
        """Genera comentarios según la expresión y los envía a la publicación."""

        expr_parts = [fragment.replace('\@', '@') for fragment in re.split(r'(?<!\\)@', expr)]
        mentions_per_comment = len(expr_parts) - 1

        if self.driver.current_url != url:
            self.driver.get(url)

        def chunk_connections() -> Iterator[str]:
            total = len(self.connections)
            step = mentions_per_comment
            for idx in range(0, (total // step) * step, step):
                yield self.connections[idx: idx + step]

        comments = Comments(chunk_connections(), expr_parts)

        for original_comment in comments.generate():
            success = False
            has_input = False
            current_comment = original_comment

            while not success:
                if not has_input:
                    try:
                        self.write_comment(current_comment)
                    except WebDriverException:
                        self.override_post_requests_js(current_comment)
                        current_comment = (
                            'Info: El mensaje real se envió correctamente. '
                            'ChromeDriver no puede mostrar aquí los caracteres especiales, '
                            'pero el comentario se publicó con éxito.'
                        )
                        self.write_comment(current_comment)

                    has_input = True

                success = self.send_comment()

                if success:
                    self.num_comments += 1
                    sleep(get_interval())

    def quit(self, message: Optional[str] = None) -> None:
        """Cierra el navegador y finaliza la ejecución con un mensaje opcional."""

        self.driver.quit()
        exit(message)

