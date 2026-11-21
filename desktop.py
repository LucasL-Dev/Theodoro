import sys


def run():
    if len(sys.argv) == 3 and sys.argv[1] == '--smoke-test':
        from theodoro.smoke import smoke_test
        return smoke_test(sys.argv[2])

    from theodoro.desktop import main
    return main()


if __name__ == '__main__':
    raise SystemExit(run())
