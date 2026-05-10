"""
PILLAR 3 + 4 entry point: Telegram Bot + Admin Backend.
Run: python3 main_bot.py
PM2: iqbot-v2-bot
"""
import asyncio
import hashlib
import hmac
import signal
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters,
)
from aiohttp import web

from database.db import init_db
from database.models.funnel import log_funnel_event
from config import BOT_TOKEN, LANDING_WEBHOOK_SECRET, OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET, OAUTH_REDIRECT_URI
from utils.logger import get_logger

logger = get_logger("main-bot")

_WEBHOOK_SECRET_BYTES = LANDING_WEBHOOK_SECRET.encode() if LANDING_WEBHOOK_SECRET else None


async def funnel_webhook(request: web.Request):
    # Verify HMAC-SHA256 signature when secret is configured
    if _WEBHOOK_SECRET_BYTES:
        signature = request.headers.get('X-Signature', '')
        body = await request.read()
        expected = hmac.new(_WEBHOOK_SECRET_BYTES, body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            logger.warning("Funnel webhook rejected: invalid signature")
            return web.Response(status=401, text='Unauthorized')
        try:
            import json
            data = json.loads(body)
        except Exception:
            logger.warning("Funnel webhook rejected: invalid JSON")
            return web.Response(status=400, text='Bad Request')
    else:
        try:
            data = await request.json()
        except Exception:
            logger.warning("Funnel webhook rejected: invalid JSON")
            return web.Response(status=400, text='Bad Request')

    try:
        event_type = str(data.get('type', 'UNKNOWN'))[:64]
        metadata = str(data.get('metadata', {}))[:1024]
        log_funnel_event(None, event_type, metadata)
    except Exception:
        logger.exception("Funnel webhook: failed to log event")
    return web.Response(text='OK')


async def oauth_callback(request: web.Request):
    """
    Handles the OAuth redirect from IQ Option after user authorization.
    IQ Option redirects here with ?code=<auth_code>&state=<state_token>.
    We exchange the code for SSID + refresh_token, store them, and notify
    the user in Telegram.
    """
    # The Telegram Bot application is stored on the aiohttp app
    bot = request.app['bot']

    code = request.rel_url.query.get('code', '')
    state = request.rel_url.query.get('state', '')
    error = request.rel_url.query.get('error', '')

    if error:
        logger.warning(f"OAuth callback received error: {error}")
        return web.Response(
            status=400,
            content_type='text/html',
            text=(
                '<html><body style="font-family:sans-serif;text-align:center;padding:40px">'
                '<h2>❌ Authorization failed</h2>'
                f'<p>{error}</p><p>Return to Telegram and try again.</p></body></html>'
            ),
        )

    if not code or not state:
        return web.Response(status=400, text='Missing code or state parameter.')

    from core.iq_oauth import pop_pending, exchange_code
    pending = pop_pending(state)
    if not pending:
        return web.Response(
            status=400, text='Authorization link expired or already used. Please try again in Telegram.'
        )

    telegram_id: int = pending['telegram_id']
    verifier: str = pending['code_verifier']

    try:
        tokens = await exchange_code(
            client_id=OAUTH_CLIENT_ID,
            code=code,
            redirect_uri=OAUTH_REDIRECT_URI,
            code_verifier=verifier,
        )
    except RuntimeError as e:
        logger.error(f"OAuth code exchange failed for telegram_id={telegram_id}: {e}")
        try:
            await bot.send_message(
                chat_id=telegram_id,
                text=f"❌ Could not connect your IQ Option account:\n\n{e}\n\nPlease try /addaccount again.",
            )
        except Exception:
            pass
        return web.Response(
            status=502,
            content_type='text/html',
            text=(
                '<html><body style="font-family:sans-serif;text-align:center;padding:40px">'
                '<h2>❌ Connection failed</h2>'
                '<p>Could not exchange the authorisation code. Check Telegram for details.</p>'
                '</body></html>'
            ),
        )

    ssid = tokens['access_token']
    refresh_tok = tokens.get('refresh_token', '')
    expires_in = tokens.get('expires_in', 1209600)

    # Look up the DB user and persist the account
    from database.models.users import get_user
    from database.models.accounts import add_oauth_account, get_account_credentials
    import os

    user = get_user(telegram_id)
    if not user:
        logger.error(f"OAuth callback: no DB user for telegram_id={telegram_id}")
        return web.Response(status=400, text='User not found.')

    # If account already exists, update its tokens; otherwise create a new one
    existing = get_account_credentials(user['id'])
    if existing:
        from database.models.accounts import store_oauth_tokens
        store_oauth_tokens(existing['id'], ssid, refresh_tok, expires_in)
        account_id = existing['id']
    else:
        account_id = add_oauth_account(
            user_id=user['id'],
            ssid=ssid,
            refresh_tok=refresh_tok,
            expires_in=expires_in,
            platform_id=int(os.getenv('PLATFORM_ID', '0')),
        )

    # Spawn watcher + log funnel event
    from bot.handlers.onboard import _post_connect
    _post_connect(user['id'], telegram_id)

    # Notify the user in Telegram
    try:
        await bot.send_message(
            chat_id=telegram_id,
            text=(
                "✅ *IQ Option account connected!*\n\n"
                "Your watcher is starting up. Use /trade when ready."
            ),
            parse_mode='Markdown',
        )
    except Exception as e:
        logger.warning(f"Could not send Telegram confirmation to {telegram_id}: {e}")

    logger.info(f"OAuth connect complete for telegram_id={telegram_id} account_id={account_id}")
    return web.Response(
        content_type='text/html',
        text=(
            '<html><body style="font-family:sans-serif;text-align:center;padding:40px">'
            '<h2>✅ Account connected!</h2>'
            '<p>Return to Telegram to start trading.</p></body></html>'
        ),
    )


def build_application() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()

    # ── User handlers ─────────────────────────────────────────
    from bot.handlers.start import (
        cmd_start, cb_have_account, cb_need_account,
        cb_back_to_user_menu, cb_back_to_admin,
    )
    from bot.handlers.verify import msg_iq_id_submission
    from bot.handlers.onboard import (
        cmd_addaccount, receive_email, receive_password, cancel_onboard, EMAIL, PASSWORD
    )
    from bot.handlers.trade import (
        cmd_trade, cb_select_pair, cb_select_timeframe,
        msg_trade_amount, cb_confirm_trade, cb_cancel_trade, cb_new_trade,
    )
    from bot.handlers.balance import cmd_balance, cb_show_balance
    from bot.handlers.leaderboard import cmd_leaderboard, cb_show_leaderboard
    from bot.handlers.settings import (
        cmd_settings, cb_show_settings, cb_show_history, cb_show_about,
    )
    from bot.handlers.help import cmd_help

    app.add_handler(CommandHandler('start', cmd_start))
    app.add_handler(CommandHandler('trade', cmd_trade))
    app.add_handler(CommandHandler('balance', cmd_balance))
    app.add_handler(CommandHandler('leaderboard', cmd_leaderboard))
    app.add_handler(CommandHandler('settings', cmd_settings))
    app.add_handler(CommandHandler('help', cmd_help))
    app.add_handler(CommandHandler('menu', cb_back_to_user_menu))
    app.add_handler(CommandHandler('history', cb_show_history))

    onboard_conv = ConversationHandler(
        entry_points=[CommandHandler('addaccount', cmd_addaccount)],
        states={
            EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_email)],
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_password)],
        },
        fallbacks=[CommandHandler('cancel', cancel_onboard)],
    )
    app.add_handler(onboard_conv)

    app.add_handler(CallbackQueryHandler(cb_have_account, pattern='^have_account$'))
    app.add_handler(CallbackQueryHandler(cb_need_account, pattern='^need_account$'))
    app.add_handler(CallbackQueryHandler(cb_select_pair, pattern='^select_pair:'))
    app.add_handler(CallbackQueryHandler(cb_select_timeframe, pattern='^select_tf:'))
    app.add_handler(CallbackQueryHandler(cb_confirm_trade, pattern='^confirm_trade:'))
    app.add_handler(CallbackQueryHandler(cb_cancel_trade, pattern='^cancel_trade$'))
    app.add_handler(CallbackQueryHandler(cb_new_trade, pattern=r'^(new_trade|open_trade)$'))

    app.add_handler(CallbackQueryHandler(cb_show_balance, pattern='^show_balance$'))
    app.add_handler(CallbackQueryHandler(cb_show_history, pattern='^show_history$'))
    app.add_handler(CallbackQueryHandler(cb_show_leaderboard, pattern='^show_leaderboard$'))
    app.add_handler(CallbackQueryHandler(cb_show_settings, pattern='^show_settings$'))
    app.add_handler(CallbackQueryHandler(cb_show_about, pattern='^show_about$'))

    app.add_handler(CallbackQueryHandler(cb_back_to_user_menu, pattern='^back_to_user_menu$'))
    app.add_handler(CallbackQueryHandler(cb_back_to_admin, pattern='^back_to_admin$'))

    # ── Admin handlers ────────────────────────────────────────
    from bot.admin.today import cmd_today
    from bot.admin.activation import cmd_activation, cb_approve, cb_reject
    from bot.admin.find_users import cmd_find
    from bot.admin.tokens import cmd_tokens, cmd_assign_token
    from bot.admin.system import cmd_system, cb_system_action
    from bot.admin.broadcast import cmd_broadcast, cb_broadcast_segment
    from bot.admin.top_traders import cmd_top_traders
    from bot.admin.funnel import cmd_funnel
    from bot.admin.audit import cmd_audit
    from bot.admin.admin_controls import cmd_admin_menu, cb_admin_action

    app.add_handler(CommandHandler('today', cmd_today))
    app.add_handler(CommandHandler('activation', cmd_activation))
    app.add_handler(CommandHandler('find', cmd_find))
    app.add_handler(CommandHandler('assign_token', cmd_assign_token))
    app.add_handler(CommandHandler('system', cmd_system))
    app.add_handler(CommandHandler('broadcast', cmd_broadcast))
    app.add_handler(CommandHandler('funnel', cmd_funnel))
    app.add_handler(CommandHandler('audit', cmd_audit))
    app.add_handler(CommandHandler('admin', cmd_admin_menu))

    app.add_handler(CallbackQueryHandler(cb_approve, pattern='^adm:approve:'))
    app.add_handler(CallbackQueryHandler(cb_reject, pattern='^adm:reject:'))
    app.add_handler(CallbackQueryHandler(cb_system_action, pattern='^sys:'))
    app.add_handler(CallbackQueryHandler(cb_admin_action, pattern='^adm:'))

    app.add_handler(CallbackQueryHandler(cb_broadcast_segment, pattern=r'^bc_seg:'))
    from bot.admin.broadcast import cb_broadcast_confirm, cb_broadcast_cancel
    app.add_handler(CallbackQueryHandler(cb_broadcast_confirm, pattern=r'^bc_confirm$'))
    app.add_handler(CallbackQueryHandler(cb_broadcast_cancel, pattern=r'^bc_cancel$'))

    # ── UNIFIED TEXT ROUTER ───────────────────────────────────
    async def text_router(update, ctx):
        if ctx.user_data.get('composing_broadcast'):
            from bot.admin.broadcast import msg_broadcast_text
            await msg_broadcast_text(update, ctx)
            return
        if ctx.user_data.get('awaiting_find_query'):
            from bot.admin.find_users import msg_find_query
            await msg_find_query(update, ctx)
            return
        if ctx.user_data.get('awaiting_iq_id'):
            await msg_iq_id_submission(update, ctx)
            return
        if ctx.user_data.get('awaiting_amount'):
            await msg_trade_amount(update, ctx)
            return
        return

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_router),
        group=1
    )

    async def error_handler(update, ctx):
        logger.exception(f"Unhandled exception in handler (update={update})", exc_info=ctx.error)

    app.add_error_handler(error_handler)

    return app


async def main():
    init_db()
    logger.info("Bot starting...")
    app = build_application()
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=False)

    funnel_app = web.Application()
    funnel_app['bot'] = app.bot  # make bot available to OAuth callback handler
    funnel_app.router.add_post('/event', funnel_webhook)
    if OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET and OAUTH_REDIRECT_URI:
        funnel_app.router.add_get('/oauth/callback', oauth_callback)
        logger.info("OAuth callback endpoint registered at /oauth/callback")
    runner = web.AppRunner(funnel_app)
    await runner.setup()
    site = web.TCPSite(runner, 'localhost', 8090)
    await site.start()
    logger.info("Funnel webhook listening on :8090")
    logger.info("Bot is running. Press Ctrl+C to stop.")

    stop_event = asyncio.Event()
    loop = asyncio.get_event_loop()
    def handle_sig():
        stop_event.set()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_sig)
        except NotImplementedError:
            pass
    await stop_event.wait()

    await app.updater.stop()
    await app.stop()
    await app.shutdown()
    await runner.cleanup()


if __name__ == '__main__':
    asyncio.run(main())
