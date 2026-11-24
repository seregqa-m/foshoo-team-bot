"""One-off owner workflow. Run with the service's env and project virtualenv."""
import argparse
import json
from fastapi import HTTPException
from core.database import SessionLocal
from modules.calendar.subscriptions import prepare_links, rebuild_links, revoke_link


def main():
    parser = argparse.ArgumentParser(description='Общие календарные ссылки по реальным комбинациям составов')
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--preview', action='store_true')
    actions.add_argument('--create', action='store_true')
    actions.add_argument('--revoke', type=int, metavar='SUBSCRIPTION_ID')
    parser.add_argument('--fingerprint', help='Отпечаток проверенного preview, обязателен для --create')
    parser.add_argument('--show', action='append', help='Явно выбранный спектакль; повторите для набора. Без параметра — реальные комбинации из таблицы.')
    args = parser.parse_args()
    if args.create and not args.fingerprint:
        parser.error('--create требует --fingerprint из --preview')
    try:
        with SessionLocal() as db:
            if args.preview:
                result = prepare_links(db, args.show)
            elif args.create:
                result = rebuild_links(db, args.fingerprint, show_names=args.show)
            else:
                revoke_link(db, args.revoke)
                result = {'revoked': args.revoke}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except HTTPException as exc:
        parser.exit(1, str(exc.detail) + '\n')


if __name__ == '__main__':
    main()
