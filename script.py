import signal
from configparser import ConfigParser
from functools import partial
from random import triangular
from re import search

from modules import Bot, Tab


ASCII = r"""


             .----------------.  .----------------.  .----------------.
            | .--------------. || .--------------. || .--------------. |
            | |  ____  ____  | || |   _    _     | || |    ______    | |
            | | |_   ||   _| | || |  | |  | |    | || |   / ____ `.  | |
            | |   | |__| |   | || |  | |__| |_   | || |   `'  __) |  | |
            | |   |  __  |   | || |  |____   _|  | || |   _  |__ '.  | |
            | |  _| |  | |_  | || |      _| |_   | || |  | \\____) |  | |
            | | |____||____| | || |     |_____|  | || |   \\______.'  | |
            | |              | || |              | || |              | |
            | '--------------' || '--------------' || '--------------' |
             '----------------'  '----------------'  '----------------'


                    Creado por: IgnacioJofreGrra
             Proyecto: GanaGramBoost


"""


def leer_configuracion() -> ConfigParser:
    parser = ConfigParser()
    parser.read('config.ini', encoding='utf8')
    return parser


def validar_configuracion(parser: ConfigParser) -> None:
    post_link = parser.get('Required', 'Post Link', fallback=None)
    save_only = parser.getboolean('Optional', 'Save Only', fallback=False)
    user_target = parser.get('Optional', 'User Target', fallback=None)
    expr = parser.get('Required', 'Expression')
    limit = parser.getint('Optional', 'Limit', fallback=None)
    force_search = parser.getboolean('Optional', 'Force Search', fallback=False)
    specific_file = parser.get('Optional', 'Specific File', fallback=None)

    if not post_link:
        if not save_only:
            exit('Debes proporcionar "Post Link" o habilitar "Save Only".')
        if save_only and not user_target:
            exit('Debes especificar "Post Link" o "User Target".')

    if specific_file:
        if save_only:
            exit('Selecciona un "Specific File" o habilita "Save Only", pero no ambos.')
        if force_search:
            exit('Selecciona un "Specific File" o habilita "Force Search", pero no ambos.')

    does_mention = bool(search(r'(?<!\\)@', expr))
    if limit:
        if force_search:
            exit('"Force Search" solo funciona si "Limit" está deshabilitado.')
        if does_mention and limit <= 0:
            exit('"Limit" debe ser mayor que 0.')

    low = parser.getint('Interval', 'Min', fallback=60)
    high = parser.getint('Interval', 'Max', fallback=120)
    weight = parser.getint('Interval', 'Weight', fallback=90)

    if not save_only and not low <= weight <= high:
        exit('"Weight" debe estar entre "Min" y "Max".')


def main() -> None:
    parser = leer_configuracion()
    validar_configuracion(parser)

    post_link = parser.get('Required', 'Post Link', fallback=None)
    expr = parser.get('Required', 'Expression')
    username = parser.get('Required', 'Username')
    password = parser.get('Required', 'Password')

    user_target = parser.get('Optional', 'User Target', fallback=None)
    from_followers = parser.getboolean('Optional', 'Followers', fallback=True)
    limit = parser.getint('Optional', 'Limit', fallback=None)
    specific_file = parser.get('Optional', 'Specific File', fallback=None)
    force_search = parser.getboolean('Optional', 'Force Search', fallback=False)
    save_only = parser.getboolean('Optional', 'Save Only', fallback=False)

    low = parser.getint('Interval', 'Min', fallback=60)
    high = parser.getint('Interval', 'Max', fallback=120)
    weight = parser.getint('Interval', 'Weight', fallback=90)

    window = parser.getboolean('Browser', 'Window', fallback=True)
    default_lang = parser.getboolean('Browser', 'Default Lang', fallback=False)
    binary_location = parser.get('Browser', 'Location', fallback=None)
    timeout = parser.getint('Browser', 'Timeout', fallback=30)

    does_mention = bool(search(r'(?<!\\)@', expr))

    print(ASCII)

    connections_type = 'followers' if from_followers else 'followings'
    connections_label = 'seguidores' if from_followers else 'seguidos'
    records_path = f'records//{connections_type}'

    bot = Bot(
        window,
        binary_location,
        default_lang,
        timeout=timeout,
        records_path=records_path,
    )

    print('Iniciando sesión en Instagram...')
    bot.log_in(username, password)
    print('¡Inicio de sesión exitoso!')

    if specific_file:
        bot.get_user_connections_from_records(specific_file=specific_file, limit=limit)

    elif save_only or does_mention:
        success = False

        if not user_target:
            print('Buscando el dueño de la publicación...')
            try:
                user_target = bot.get_user_from_post(post_link)  # type: ignore[arg-type]
                print('¡Dueño de la publicación encontrado!')
            except Exception as exc:  # noqa: BLE001
                print(f'No se pudo detectar automáticamente el dueño del post: {exc}')
                bot.quit('Configura "User Target" en config.ini dentro de [Optional] o verifica el enlace de la publicación.')

        assert user_target  # Seguridad para el tipado estático

        print(f'Buscando los {connections_label} de {user_target} en los registros...')
        success = bot.get_user_connections_from_records(
            user_target,
            limit=limit,
            followers=from_followers,
        )

        if not success or force_search:
            if limit:
                print(f'Obtenidos {len(bot.connections)}/{limit} {connections_label}. Todavía faltan...')

            print(f'Buscando los {connections_label} de {user_target} directamente en Instagram...')

            count_connections_in_record = len(bot.connections)
            to_quit = False
            original_sigint = signal.getsignal(signal.SIGINT)

            try:
                user_target_url = bot.url_base + user_target

                if save_only:
                    bot.driver.get(user_target_url)
                    bot.get_user_connections_from_web(limit, from_followers, force_search)
                else:
                    with Tab(bot.driver, user_target_url):
                        bot.get_user_connections_from_web(limit, from_followers, force_search)

            except KeyboardInterrupt:
                to_quit = True

            signal.signal(signal.SIGINT, signal.SIG_IGN)
            connections_added_count = len(bot.connections) - count_connections_in_record

            if connections_added_count:
                bot.save_connections(user_target, bot.connections[-connections_added_count:])

            if to_quit:
                bot.quit(
                    f'Terminación anticipada. Se agregaron {connections_added_count} nuevos. '
                    f'Ahora hay {len(bot.connections)} {connections_label} en los registros.'
                )
            else:
                print(
                    f'Se encontraron {connections_added_count} en Instagram. '
                    f'Ahora hay {len(bot.connections)} {connections_label} en los registros.'
                )
                signal.signal(signal.SIGINT, original_sigint)

        else:
            print(
                f'¡{len(bot.connections)} {connections_label} encontrados en los registros! '
                'No es necesario buscar en Instagram.'
            )

    if not save_only:
        if post_link is None:
            raise RuntimeError('"Post Link" no puede ser vacío cuando "Save Only" está deshabilitado.')

        print('¡Vamos a ganar este sorteo! Comenzando a comentar...')

        get_interval = partial(triangular, low, high, weight)

        try:
            bot.comment_post(post_link, expr, get_interval)
        except Exception:  # noqa: BLE001
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            bot.quit(f'Terminación anticipada. Se enviaron {bot.num_comments} comentarios hasta ahora.')
        else:
            print(f'¡Se enviaron todos los comentarios posibles! Un total de {bot.num_comments} comentarios.')


if __name__ == '__main__':
    main()

