import argparse
import sys


def cmd_load_data(args: argparse.Namespace) -> None:
    from scripts.load_data import load

    counts, skipped = load(force=args.force, dry_run=args.dry_run)
    if skipped:
        print("Снапшот уже загружен, пропуск. Повторить: --force")
        return
    prefix = "Разобрано" if args.dry_run else "Загружено"
    for name, count in counts.items():
        print(f"{prefix} {name}: {count}")


def cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn

    from src.config.settings import get_settings
    from src.webapp.app import create_app

    settings = get_settings()
    uvicorn.run(create_app(), host=settings.app_host, port=settings.app_port)


def cmd_mcp(args: argparse.Namespace) -> None:
    raise SystemExit("Команда mcp появится на этапе 2 (MCP-сервер).")


def main() -> int:
    parser = argparse.ArgumentParser(prog="app.py", description="ИИ-агент проверки контрагентов")
    commands = parser.add_subparsers(dest="command", required=True)

    load_parser = commands.add_parser("load-data", help="залить снапшот JSON в Postgres")
    load_parser.add_argument("--force", action="store_true", help="перезалить, даже если снапшот не менялся")
    load_parser.add_argument("--dry-run", action="store_true", help="разобрать файл без записи в БД")
    load_parser.set_defaults(func=cmd_load_data)

    serve_parser = commands.add_parser("serve", help="запустить FastAPI и UI")
    serve_parser.set_defaults(func=cmd_serve)

    mcp_parser = commands.add_parser("mcp", help="запустить MCP-сервер")
    mcp_parser.set_defaults(func=cmd_mcp)

    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
