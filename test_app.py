import os
import logging
import math
import asyncio
from metaapi_cloud_sdk import MetaApi
from telegram import ParseMode, Update
from telegram.ext import CommandHandler, Updater, CallbackContext

# MetaAPI Credentials
API_KEY = os.environ.get("API_KEY")
ACCOUNT_ID = os.environ.get("ACCOUNT_ID")

# Telegram Credentials
TOKEN = os.environ.get("TOKEN")
TELEGRAM_USER = os.environ.get("TELEGRAM_USER")

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FX Symbols and Risk Factor
SYMBOLS = ['AUDUSD', 'EURUSD', 'GBPUSD', 'USDJPY', 'USDCAD', 'XAUUSD', 'XAGUSD']
RISK_FACTOR = float(os.environ.get("RISK_FACTOR", 0.01))


def parse_signal(signal: str) -> dict:
    """Parses a signal message into trade details."""
    lines = [line.strip() for line in signal.splitlines()]
    trade = {}

    if 'buy' in lines[0].lower():
        trade['OrderType'] = 'Buy'
    elif 'sell' in lines[0].lower():
        trade['OrderType'] = 'Sell'
    else:
        return {}

    trade['Symbol'] = lines[0].split()[-1].upper()
    if trade['Symbol'] not in SYMBOLS:
        return {}

    trade['Entry'] = 'NOW' if trade['OrderType'] in ['Buy', 'Sell'] else float(lines[1].split()[-1])
    trade['StopLoss'] = float(lines[2].split()[-1])
    trade['TP'] = [float(lines[3].split()[-1])]
    if len(lines) > 4:
        trade['TP'].append(float(lines[4].split()[-1]))

    trade['RiskFactor'] = RISK_FACTOR
    return trade


def calculate_position_size(balance: float, trade: dict) -> None:
    """Calculates position size based on balance, risk, and stop loss."""
    multiplier = 0.0001 if trade['Symbol'] not in ['XAUUSD', 'XAGUSD'] else 0.1
    stop_loss_pips = abs(round((trade['StopLoss'] - float(trade['Entry'])) / multiplier))
    trade['PositionSize'] = math.floor(((balance * trade['RiskFactor']) / stop_loss_pips) / 10 * 100) / 100


async def connect_metatrader(trade: dict) -> None:
    """Connect to MetaTrader and execute trade."""
    try:
        api = MetaApi(API_KEY)
        account = await api.metatrader_account_api.get_account(ACCOUNT_ID)

        if account.state != 'DEPLOYED':
            await account.deploy()
        await account.wait_connected()

        connection = account.get_rpc_connection()
        await connection.connect()
        await connection.wait_synchronized()

        if trade['Entry'] == 'NOW':
            price = await connection.get_symbol_price(trade['Symbol'])
            trade['Entry'] = price['bid'] if trade['OrderType'] == 'Buy' else price['ask']
    except Exception as e:
        logger.error(f"MetaTrader connection error: {e}")
        raise


async def place_trade(update: Update, context: CallbackContext) -> None:
    """Handles the trade command and places trade on MetaTrader."""
    try:
        trade = parse_signal(update.message.text)
        if not trade:
            update.message.reply_text("Invalid trade format. Please use: BUY/SELL SYMBOL Entry SL TP.")
            return

        await connect_metatrader(trade)

        # Fetch dynamic balance
        account_info = await connection.get_account_information()
        balance = account_info['balance']

        calculate_position_size(balance, trade)
        update.message.reply_text(f"Trade placed: {trade['OrderType']} {trade['Symbol']} at {trade['Entry']}.")
    except ValueError as ve:
        update.message.reply_text(f"Value error: {ve}. Check your inputs.")
        logger.error(f"ValueError: {ve}")
    except Exception as e:
        update.message.reply_text(f"Error occurred while placing the trade: {e}")
        logger.error(f"Exception: {e}")


async def account_info(update: Update, context: CallbackContext) -> None:
    """Handles the /account_info command and returns account details."""
    try:
        api = MetaApi(API_KEY)
        account = await api.metatrader_account_api.get_account(ACCOUNT_ID)

        if account.state != 'DEPLOYED':
            await account.deploy()
        await account.wait_connected()

        connection = account.get_rpc_connection()
        await connection.connect()
        await connection.wait_synchronized()

        # Get account details
        account_info = await connection.get_account_information()

        balance = account_info['balance']
        equity = account_info['equity']
        margin = account_info['margin']
        free_margin = account_info['freeMargin']

        info_message = (
            f"**Account Information**\n"
            f"Balance: {balance}\n"
            f"Equity: {equity}\n"
            f"Margin: {margin}\n"
            f"Free Margin: {free_margin}"
        )

        update.message.reply_text(info_message, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        update.message.reply_text(f"Error fetching account information: {e}")
        logger.error(f"Error in account_info: {e}")


def start(update: Update, _: CallbackContext) -> None:
    """Welcomes the user."""
    update.message.reply_text("Welcome! Use /trade to place a trade or /account_info for account details.")


def help_command(update: Update, _: CallbackContext) -> None:
    """Displays help message."""
    help_text = """
    Welcome to the Trading Bot Help!

    This bot is designed to assist with managing and monitoring your MetaTrader account. Below are the commands you can use and what they do:

    **Available Commands:**

    1. **/start** - Initializes the bot and gives a brief introduction.
       - Use this command to begin interacting with the bot.

    2. **/help** - Displays this help message.
       - If you're ever unsure about a command or need guidance, use this to get detailed instructions.

    3. **/account_info** - Provides a summary of your MetaTrader account, including balance, equity, margin, and free margin.
       - Usage: Type `/account_info` to get a complete snapshot of your account's key metrics.

    **Additional Information:**

    - **Risk Management:** Ensure you understand your risk exposure by regularly checking your margin and free margin with the relevant commands.

    - **Error Handling:** In case something goes wrong, you will receive a detailed error message so you can troubleshoot effectively.

    For further assistance, feel free to reach out!

    Happy Trading! 🚀
    """
    update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


def error_handler(update: Update, context: CallbackContext) -> None:
    """Logs errors caused by updates and notifies the user."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

    # Notify the user of the error
    update.message.reply_text("Sorry, an error occurred while processing your request. Please try again later.")


def main() -> None:
    """Starts the Telegram bot."""
    updater = Updater(TOKEN)
    dispatcher = updater.dispatcher

    # Commands
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("help", help_command))
    dispatcher.add_handler(CommandHandler("trade", place_trade))
    dispatcher.add_handler(CommandHandler("account_info", account_info))  # Add the account_info handler

    # Log all errors
    dispatcher.add_error_handler(error_handler)

    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()
