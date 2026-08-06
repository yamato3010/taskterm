"""todo - エントリーポイント"""

from .app import TodoApp


def main() -> None:
    app = TodoApp()
    app.run()


if __name__ == "__main__":
    main()
