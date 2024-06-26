import configparser
import tkinter as tk
from tkinter import ttk
from tkinter import font
from math import ceil
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.order import *
import threading
import time
from PIL import Image, ImageTk  # Import from PIL
import sys
import io

# Initialize the configuration parser
config = configparser.ConfigParser()
config.read('defaults.ini')

# Read connection details
host = config.get('CONNECTION', 'host')
port = config.getint('CONNECTION', 'port')
clientId = config.getint('CONNECTION', 'clientId')

class IBapi(EWrapper, EClient):
    def __init__(self, equity, log_widget):
        EClient.__init__(self, self)
        self.equity = equity
        self.log_widget = log_widget
        self.nextorderId = None  # Initialize nextorderId

    def nextValidId(self, orderId: int):
        super().nextValidId(orderId)
        self.nextorderId = orderId
        self.log(f'The next valid order ID is: {self.nextorderId}')

    def accountSummary(self, reqId: int, account: str, tag: str, value: str, currency: str):
        self.log(f"<{reqId}> Account: {account}\n{tag} Value: {float(value):,} Currency: {currency}")
        if tag == 'NetLiquidation':
            self.equity.delete(0, 'end')
            self.equity.insert(0, value)

    def accountSummaryEnd(self, reqId: int):
        self.log(f"<{reqId}> Account Summary End")

    def BracketOrder(self, parentOrderId: int, action: str, quantity: float, stopPrice: float, takeProfitLimitPrice: float, stopLossPrice: float):
        parent = Order()
        size = int(ceil(quantity))

        parent.orderId = parentOrderId
        parent.action = action
        parent.orderType = "STP LMT"
        parent.auxPrice = stopPrice
        parent.lmtPrice = float(round(stopPrice * (1+get_buy_limit_threshold()), 2))
        parent.totalQuantity = size
        parent.tif = "GTC"
        parent.transmit = False

        takeProfit = Order()
        if takeProfitLimitPrice > 0:
            takeProfit.orderId = parent.orderId + 1
            takeProfit.action = "SELL" if action == "BUY" else "BUY"
            takeProfit.orderType = "LMT"
            takeProfit.totalQuantity = size
            takeProfit.lmtPrice = takeProfitLimitPrice
            takeProfit.parentId = parentOrderId
            takeProfit.tif = "GTC"
            takeProfit.transmit = False

        stopLoss = Order()
        stopLoss.orderId = parent.orderId + 2
        stopLoss.action = "SELL" if action == "BUY" else "BUY"
        stopLoss.orderType = "STP"
        stopLoss.auxPrice = stopLossPrice
        stopLoss.totalQuantity = size
        stopLoss.parentId = parentOrderId
        stopLoss.tif = "GTC"
        stopLoss.transmit = True

        if takeProfitLimitPrice > 0:
            bracketOrder = [parent, takeProfit, stopLoss]
        else:
            bracketOrder = [parent, stopLoss]

        return bracketOrder

    def disconnect_IBAPI(self):
        self.log("Disconnecting from IB API")
        self.done = True
        self.disconnect()

    def log(self, message):
        self.log_widget.insert(tk.END, message + "\n")
        self.log_widget.see(tk.END)

# Function to run the API loop
def run_loop():
    app.run()

# Function to create bracket order
def create_bracket_order(contract, order_id, shares, buy_stop, sell_limit_profit, stop_loss):
    bracket = app.BracketOrder(order_id, "BUY", shares, buy_stop, sell_limit_profit, stop_loss)
    for o in bracket:
        o.eTradeOnly = False
        o.firmQuoteOnly = False
        o.tif = "GTC"  # Ensure order is GTC
        app.placeOrder(o.orderId, contract, o)
    app.nextorderId += len(bracket)
    return bracket

# Function to execute order
def execute_order():
    try:
        ticker = entry_ticker.get()
        if not ticker:
            raise ValueError("Ticker cannot be empty")

        core_shares = int(float(label_core_shares['text'])) if label_core_shares['text'] != 'N/A' else 0
        pyr1_shares = int(float(label_pyr1_shares['text'])) if label_pyr1_shares['text'] != 'N/A' else 0
        pyr2_shares = int(float(label_pyr2_shares['text'])) if label_pyr2_shares['text'] != 'N/A' else 0

        contract = Contract()
        contract.symbol = ticker
        contract.secType = "STK"
        contract.currency = "USD"
        contract.exchange = "SMART"
        contract.primaryExchange = "ISLAND"

        if core_shares > 0:
            order_id = app.nextorderId
            create_bracket_order(contract, order_id, core_shares, float(entry_core_buy_stop.get()),
                                 float(label_core_sell_limit_profit['text'].replace('$', '')), float(entry_core_stop_loss.get()))

        if pyr1_shares > 0:
            order_id = app.nextorderId
            create_bracket_order(contract, order_id, pyr1_shares, float(entry_pyr1_buy_stop.get()),
                                 float(label_pyr1_sell_limit_profit['text'].replace('$', '')), float(entry_pyr1_stop_loss.get()))

        if pyr2_shares > 0:
            order_id = app.nextorderId
            create_bracket_order(contract, order_id, pyr2_shares, float(entry_pyr2_buy_stop.get()),
                                 float(label_pyr2_sell_limit_profit['text'].replace('$', '')), float(entry_pyr2_stop_loss.get()))

    except ValueError as e:
        app.log(f"Input error: {e}")
    except Exception as e:
        app.log(f"Unexpected error: {e}")

# Function to calculate
def calculate():
    try:
        equity = float(entry_equity.get() or 0)
        risk_per_full_pos = float(entry_risk_per_full_pos.get() or 0) / 100
        full_position_size = float(entry_full_position_size.get() or 0) / 100
        r_target = float(entry_r_target.get() or 0)

        pos_size_dict = {
            "Full": full_position_size,
            "Half": full_position_size / 2,
            "Quarter": full_position_size / 4,
            "None": 0
        }

        core_pos_size = pos_size_dict[combobox_core_pos_size.get()]
        pyr1_pos_size = pos_size_dict[combobox_pyr1_pos_size.get()]
        pyr2_pos_size = pos_size_dict[combobox_pyr2_pos_size.get()]

        core_buy_stop = float(entry_core_buy_stop.get() or 0)
        core_stop_loss = float(entry_core_stop_loss.get() or 0)
        core_stop_percentage = (core_buy_stop - core_stop_loss) / core_buy_stop * 100 if core_buy_stop else 0
        core_r_equity = equity * risk_per_full_pos * core_pos_size / full_position_size if full_position_size else 0
        core_sell_limit_profit = core_buy_stop * (1 + core_stop_percentage / 100 * r_target) if core_buy_stop else 0
        core_shares = ceil((equity * core_pos_size) / core_buy_stop / 2) * 2 if core_buy_stop else 0
        core_value_at_risk = core_shares * (core_buy_stop - core_stop_loss)

        pyr1_buy_stop = float(entry_pyr1_buy_stop.get() or 0)
        pyr1_stop_loss = float(entry_pyr1_stop_loss.get() or 0)
        pyr1_stop_percentage = (pyr1_buy_stop - pyr1_stop_loss) / pyr1_buy_stop * 100 if pyr1_buy_stop else 0
        pyr1_r_equity = equity * risk_per_full_pos * pyr1_pos_size / full_position_size if full_position_size else 0
        pyr1_sell_limit_profit = pyr1_buy_stop * (1 + pyr1_stop_percentage / 100 * r_target) if pyr1_buy_stop else 0
        pyr1_shares = core_shares * (pyr1_pos_size / core_pos_size) if core_pos_size else 0
        pyr1_value_at_risk = pyr1_shares * (pyr1_buy_stop - pyr1_stop_loss)

        pyr2_buy_stop = float(entry_pyr2_buy_stop.get() or 0)
        pyr2_stop_loss = float(entry_pyr2_stop_loss.get() or 0)
        pyr2_stop_percentage = (pyr2_buy_stop - pyr2_stop_loss) / pyr2_buy_stop * 100 if pyr2_buy_stop else 0
        pyr2_r_equity = equity * risk_per_full_pos * pyr2_pos_size / full_position_size if full_position_size else 0
        pyr2_sell_limit_profit = pyr2_buy_stop * (1 + pyr2_stop_percentage / 100 * r_target) if pyr2_buy_stop else 0
        pyr2_shares = core_shares * (pyr2_pos_size / core_pos_size) if core_pos_size else 0
        pyr2_value_at_risk = pyr2_shares * (pyr2_buy_stop - pyr2_stop_loss)

        update_labels(core_stop_percentage, core_value_at_risk, core_r_equity, core_sell_limit_profit, core_shares,
                      pyr1_stop_percentage, pyr1_value_at_risk, pyr1_r_equity, pyr1_sell_limit_profit, pyr1_shares,
                      pyr2_stop_percentage, pyr2_value_at_risk, pyr2_r_equity, pyr2_sell_limit_profit, pyr2_shares)

    except ValueError as e:
        app.log(f"Input error: {e}")
    except Exception as e:
        app.log(f"Unexpected error: {e}")

# Helper function to update labels
def update_labels(core_stop_percentage, core_value_at_risk, core_r_equity, core_sell_limit_profit, core_shares,
                  pyr1_stop_percentage, pyr1_value_at_risk, pyr1_r_equity, pyr1_sell_limit_profit, pyr1_shares,
                  pyr2_stop_percentage, pyr2_value_at_risk, pyr2_r_equity, pyr2_sell_limit_profit, pyr2_shares):
    label_core_stop_percentage['text'] = f"{core_stop_percentage:.2f}%" if core_stop_percentage else "N/A"
    label_core_value_at_risk['text'] = f"${core_value_at_risk:.2f}"
    label_core_r_equity['text'] = f"${core_r_equity:.2f}"
    label_core_sell_limit_profit['text'] = f"${core_sell_limit_profit:.2f}" if core_sell_limit_profit else "N/A"
    label_core_shares['text'] = f"{core_shares}" if core_shares else "N/A"

    label_pyr1_stop_percentage['text'] = f"{pyr1_stop_percentage:.2f}%" if pyr1_stop_percentage else "N/A"
    label_pyr1_value_at_risk['text'] = f"${pyr1_value_at_risk:.2f}"
    label_pyr1_r_equity['text'] = f"${pyr1_r_equity:.2f}"
    label_pyr1_sell_limit_profit['text'] = f"${pyr1_sell_limit_profit:.2f}" if pyr1_sell_limit_profit else "N/A"
    label_pyr1_shares['text'] = f"{pyr1_shares}" if pyr1_shares else "N/A"

    label_pyr2_stop_percentage['text'] = f"{pyr2_stop_percentage:.2f}%" if pyr2_stop_percentage else "N/A"
    label_pyr2_value_at_risk['text'] = f"${pyr2_value_at_risk:.2f}"
    label_pyr2_r_equity['text'] = f"${pyr2_r_equity:.2f}"
    label_pyr2_sell_limit_profit['text'] = f"${pyr2_sell_limit_profit:.2f}" if pyr2_sell_limit_profit else "N/A"
    label_pyr2_shares['text'] = f"{pyr2_shares}" if pyr2_shares else "N/A"

# Format number with thousands separator
def format_number(value):
    try:
        return f"{float(value):,}"
    except ValueError:
        return value  # In case the value cannot be converted to float

def get_buy_limit_threshold():
    try:
        return float(entry_buy_limit_thresh.get()) / 100
    except ValueError:
        return 0.01  # Default value if the entry is empty or invalid


# Function to save the defaults
def save_defaults():
    config['DEFAULTS'] = {
        'Risk per Full Pos %': entry_risk_per_full_pos.get(),
        'Full Position Size %': entry_full_position_size.get(),
        'Buy Limit Thresh %': entry_buy_limit_thresh.get(),
        'R Target': entry_r_target.get()
    }
    with open('defaults.ini', 'w') as configfile:
        config.write(configfile)

# Load the configuration file and set defaults
def load_defaults():
    if 'DEFAULTS' in config:
        entry_risk_per_full_pos.insert(0, config['DEFAULTS'].get('risk per full pos %', ''))
        entry_full_position_size.insert(0, config['DEFAULTS'].get('full position size %', ''))
        entry_buy_limit_thresh.insert(0, config['DEFAULTS'].get('buy limit thresh %', ''))
        entry_r_target.insert(0, config['DEFAULTS'].get('r target', ''))

# Create the main window
root = tk.Tk()
root.title("IBKR Pyramid Order Tool")
root.configure(bg='#2b2b2b')  # Dark background

# Set the icon for the taskbar
root.iconbitmap("logo.ico")

# Load the logo image and set it as the icon for the title bar
logo_image = Image.open("logo.png")  # Replace with the actual path to your logo image
logo_photo = ImageTk.PhotoImage(logo_image)
root.iconphoto(True, logo_photo)

def on_closing():
    app.disconnect_IBAPI()
    root.destroy()

root.protocol("WM_DELETE_WINDOW", on_closing)

style = ttk.Style()
style.theme_use('default')

# Define custom style for frames
style.configure("Custom.TLabelframe", background='#346326', foreground='#FF9E1B', font=('Aptos', 14, 'bold'))
style.configure("Custom.TLabelframe.Label", background='#346326', foreground='#FF9E1B', font=('Aptos', 14, 'bold'))

# Set the theme for the labels and entries
style.configure("TLabel", background='#346326', foreground='white', font=('Aptos', 12))
style.configure("TButton", background='#3c3c3c', foreground='#FF9E1B', font=('Aptos', 12, 'bold'))
style.configure("TEntry", background='#3c3c3c', foreground='#386227', font=('Aptos', 12))
style.configure("TCombobox", background='#3c3c3c', foreground='#386227', font=('Aptos', 12))

# Create a label to display the image
logo_label = ttk.Label(root, image=logo_photo, background='#2b2b2b')
logo_label.image = logo_photo  # Keep a reference to avoid garbage collection
logo_label.grid(row=0, column=2, padx=10, pady=10, sticky="ns", rowspan=1)

# Configure the columns to have equal weight
root.grid_columnconfigure(0, weight=1)
root.grid_columnconfigure(1, weight=1)
root.grid_columnconfigure(2, weight=1)

# Configure the rows to have equal weight (optional, if needed)
root.grid_rowconfigure(0, weight=1)
root.grid_rowconfigure(1, weight=1)
root.grid_rowconfigure(2, weight=1)

# Portfolio Frame
frame_portfolio = ttk.LabelFrame(root, text="Portfolio", style="Custom.TLabelframe")
frame_portfolio.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

ttk.Label(frame_portfolio, text="Equity:").grid(row=0, column=0, sticky="e", padx=5, pady=2)
entry_equity = ttk.Entry(frame_portfolio)
entry_equity.grid(row=0, column=1, padx=5, pady=2)

ttk.Label(frame_portfolio, text="Risk per Full Pos %:").grid(row=1, column=0, sticky="e", padx=5, pady=2)
entry_risk_per_full_pos = ttk.Entry(frame_portfolio)
entry_risk_per_full_pos.grid(row=1, column=1, padx=5, pady=2)

ttk.Label(frame_portfolio, text="Full Position Size %:").grid(row=2, column=0, sticky="e", padx=5, pady=2)
entry_full_position_size = ttk.Entry(frame_portfolio)
entry_full_position_size.grid(row=2, column=1, padx=5, pady=2)

ttk.Label(frame_portfolio, text="Buy Stop Limit %:").grid(row=3, column=0, sticky="e", padx=5, pady=2)
entry_buy_limit_thresh = ttk.Entry(frame_portfolio)
entry_buy_limit_thresh.grid(row=3, column=1, padx=5, pady=2)

ttk.Label(frame_portfolio, text="R Target:").grid(row=4, column=0, sticky="e", padx=5, pady=2)
entry_r_target = ttk.Entry(frame_portfolio)
entry_r_target.grid(row=4, column=1, padx=5, pady=2)

ttk.Label(frame_portfolio, text="Ticker:").grid(row=5, column=0, sticky="e", padx=5, pady=2)
entry_ticker = ttk.Entry(frame_portfolio)
entry_ticker.grid(row=5, column=1, padx=5, pady=2)

# Load default values from configuration file
load_defaults()

# Core Position Frame
frame_core_position = ttk.LabelFrame(root, text="Core Position", style="Custom.TLabelframe")
frame_core_position.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")

ttk.Label(frame_core_position, text="Buy Stop $:").grid(row=0, column=0, sticky="e", padx=5, pady=2)
entry_core_buy_stop = ttk.Entry(frame_core_position)
entry_core_buy_stop.grid(row=0, column=1, padx=5, pady=2)

ttk.Label(frame_core_position, text="Stop Loss $:").grid(row=1, column=0, sticky="e", padx=5, pady=2)
entry_core_stop_loss = ttk.Entry(frame_core_position)
entry_core_stop_loss.grid(row=1, column=1, padx=5, pady=2)

ttk.Label(frame_core_position, text="Pos Size %:").grid(row=2, column=0, sticky="e", padx=5, pady=2)
combobox_core_pos_size = ttk.Combobox(frame_core_position, values=["Full", "Half", "Quarter", "None"], state="readonly")
combobox_core_pos_size.grid(row=2, column=1, padx=5, pady=2)
combobox_core_pos_size.current(1)  # Set default to "Half"

ttk.Label(frame_core_position, text="Stop %:").grid(row=3, column=0, sticky="e", padx=5, pady=2)
label_core_stop_percentage = ttk.Label(frame_core_position, text="0.00%")
label_core_stop_percentage.grid(row=3, column=1, sticky="w", padx=5, pady=2)

ttk.Label(frame_core_position, text="Value at Risk:").grid(row=4, column=0, sticky="e", padx=5, pady=2)
label_core_value_at_risk = ttk.Label(frame_core_position, text="$0.00")
label_core_value_at_risk.grid(row=4, column=1, sticky="w", padx=5, pady=2)

ttk.Label(frame_core_position, text="R $ Equity:").grid(row=5, column=0, sticky="e", padx=5, pady=2)
label_core_r_equity = ttk.Label(frame_core_position, text="$0.00")
label_core_r_equity.grid(row=5, column=1, sticky="w", padx=5, pady=2)

ttk.Label(frame_core_position, text="Sell Limit Profit $:").grid(row=6, column=0, sticky="e", padx=5, pady=2)
label_core_sell_limit_profit = ttk.Label(frame_core_position, text="$0.00")
label_core_sell_limit_profit.grid(row=6, column=1, sticky="w", padx=5, pady=2)

ttk.Label(frame_core_position, text="Assumed Shares:").grid(row=7, column=0, sticky="e", padx=5, pady=2)
label_core_shares = ttk.Label(frame_core_position, text="N/A")
label_core_shares.grid(row=7, column=1, sticky="w", padx=5, pady=2)

# Pyramid 1 Frame
frame_pyr1 = ttk.LabelFrame(root, text="Pyramid 1", style="Custom.TLabelframe")
frame_pyr1.grid(row=1, column=1, padx=10, pady=10, sticky="nsew")

ttk.Label(frame_pyr1, text="Buy Stop $:").grid(row=0, column=0, sticky="e", padx=5, pady=2)
entry_pyr1_buy_stop = ttk.Entry(frame_pyr1)
entry_pyr1_buy_stop.grid(row=0, column=1, padx=5, pady=2)

ttk.Label(frame_pyr1, text="Stop Loss $:").grid(row=1, column=0, sticky="e", padx=5, pady=2)
entry_pyr1_stop_loss = ttk.Entry(frame_pyr1)
entry_pyr1_stop_loss.grid(row=1, column=1, padx=5, pady=2)

ttk.Label(frame_pyr1, text="Pos Size %:").grid(row=2, column=0, sticky="e", padx=5, pady=2)
combobox_pyr1_pos_size = ttk.Combobox(frame_pyr1, values=["Full", "Half", "Quarter", "None"], state="readonly")
combobox_pyr1_pos_size.grid(row=2, column=1, padx=5, pady=2)
combobox_pyr1_pos_size.current(1)  # Set default to "Half"

ttk.Label(frame_pyr1, text="Stop %:").grid(row=3, column=0, sticky="e", padx=5, pady=2)
label_pyr1_stop_percentage = ttk.Label(frame_pyr1, text="0.00%")
label_pyr1_stop_percentage.grid(row=3, column=1, sticky="w", padx=5, pady=2)

ttk.Label(frame_pyr1, text="Value at Risk:").grid(row=4, column=0, sticky="e", padx=5, pady=2)
label_pyr1_value_at_risk = ttk.Label(frame_pyr1, text="$0.00")
label_pyr1_value_at_risk.grid(row=4, column=1, sticky="w", padx=5, pady=2)

ttk.Label(frame_pyr1, text="R $ Equity:").grid(row=5, column=0, sticky="e", padx=5, pady=2)
label_pyr1_r_equity = ttk.Label(frame_pyr1, text="$0.00")
label_pyr1_r_equity.grid(row=5, column=1, sticky="w", padx=5, pady=2)

ttk.Label(frame_pyr1, text="Sell Limit Profit $:").grid(row=6, column=0, sticky="e", padx=5, pady=2)
label_pyr1_sell_limit_profit = ttk.Label(frame_pyr1, text="$0.00")
label_pyr1_sell_limit_profit.grid(row=6, column=1, sticky="w", padx=5, pady=2)

ttk.Label(frame_pyr1, text="Assumed Shares:").grid(row=7, column=0, sticky="e", padx=5, pady=2)
label_pyr1_shares = ttk.Label(frame_pyr1, text="N/A")
label_pyr1_shares.grid(row=7, column=1, sticky="w", padx=5, pady=2)

# Pyramid 2 Frame
frame_pyr2 = ttk.LabelFrame(root, text="Pyramid 2", style="Custom.TLabelframe")
frame_pyr2.grid(row=1, column=2, padx=10, pady=10, sticky="nsew")

ttk.Label(frame_pyr2, text="Buy Stop $:").grid(row=0, column=0, sticky="e", padx=5, pady=2)
entry_pyr2_buy_stop = ttk.Entry(frame_pyr2)
entry_pyr2_buy_stop.grid(row=0, column=1, padx=5, pady=2)

ttk.Label(frame_pyr2, text="Stop Loss $:").grid(row=1, column=0, sticky="e", padx=5, pady=2)
entry_pyr2_stop_loss = ttk.Entry(frame_pyr2)
entry_pyr2_stop_loss.grid(row=1, column=1, padx=5, pady=2)

ttk.Label(frame_pyr2, text="Pos Size %:").grid(row=2, column=0, sticky="e", padx=5, pady=2)
combobox_pyr2_pos_size = ttk.Combobox(frame_pyr2, values=["Full", "Half", "Quarter", "None"], state="readonly")
combobox_pyr2_pos_size.grid(row=2, column=1, padx=5, pady=2)
combobox_pyr2_pos_size.current(3)  # Set default to "None"

ttk.Label(frame_pyr2, text="Stop %:").grid(row=3, column=0, sticky="e", padx=5, pady=2)
label_pyr2_stop_percentage = ttk.Label(frame_pyr2, text="0.00%")
label_pyr2_stop_percentage.grid(row=3, column=1, sticky="w", padx=5, pady=2)

ttk.Label(frame_pyr2, text="Value at Risk:").grid(row=4, column=0, sticky="e", padx=5, pady=2)
label_pyr2_value_at_risk = ttk.Label(frame_pyr2, text="$0.00")
label_pyr2_value_at_risk.grid(row=4, column=1, sticky="w", padx=5, pady=2)

ttk.Label(frame_pyr2, text="R $ Equity:").grid(row=5, column=0, sticky="e", padx=5, pady=2)
label_pyr2_r_equity = ttk.Label(frame_pyr2, text="$0.00")
label_pyr2_r_equity.grid(row=5, column=1, sticky="w", padx=5, pady=2)

ttk.Label(frame_pyr2, text="Sell Limit Profit $:").grid(row=6, column=0, sticky="e", padx=5, pady=2)
label_pyr2_sell_limit_profit = ttk.Label(frame_pyr2, text="$0.00")
label_pyr2_sell_limit_profit.grid(row=6, column=1, sticky="w", padx=5, pady=2)

ttk.Label(frame_pyr2, text="Assumed Shares:").grid(row=7, column=0, sticky="e", padx=5, pady=2)
label_pyr2_shares = ttk.Label(frame_pyr2, text="N/A")
label_pyr2_shares.grid(row=7, column=1, sticky="w", padx=5, pady=2)

# Log Frame
frame_log = ttk.LabelFrame(root, text="Status", style="Custom.TLabelframe")
frame_log.grid(row=0, column=1, padx=1, pady=10, sticky="nsew", columnspan=1)

log_text = tk.Text(frame_log, wrap='word', height=5, bg='#2b2b2b', fg='white', font=('Aptos', 10), width=1)
log_text.grid(row=0, column=0, padx=5, pady=5, sticky="nsew", columnspan=1)
frame_log.grid_rowconfigure(0, weight=1)
frame_log.grid_columnconfigure(0, weight=1)

# Connect Data Text
connect_data = tk.Text(frame_log, wrap='word', height=1, bg='#2b2b2b', fg='white', font=('Aptos', 10), width=1)
connect_data.grid(row=1, column=0, padx=5, pady=5, sticky="ew", columnspan=1)
frame_log.grid_rowconfigure(1, weight=0)
frame_log.grid_columnconfigure(0, weight=1)

# Calculate Button
button_calculate = ttk.Button(root, text="Calculate", command=calculate)
button_calculate.grid(row=2, column=0, padx=10, pady=10, sticky="ns")

# Execute Order Button
button_execute = ttk.Button(root, text="Execute Order", command=execute_order)
button_execute.grid(row=2, column=1, padx=10, pady=10, sticky="ns")

# Save Defaults Button
button_save_defaults = ttk.Button(root, text="Save Defaults", command=save_defaults)
button_save_defaults.grid(row=2, column=2, padx=10, pady=10, sticky="ns")

# Start the API connection
app = IBapi(entry_equity, log_text)
app.connect(host, port, clientId)

time.sleep(1)  # Sleep interval to allow time for connection to server

app.reqAccountSummary(1337, "All", 'NetLiquidation')

# Start the socket in a thread
api_thread = threading.Thread(target=run_loop, daemon=True)
api_thread.start()

connect_data.delete(1.0, tk.END)
connect_data.insert(tk.END, f"Host: {host}, Port: {port}, clientID: {clientId}")

# Start the GUI event loop
root.mainloop()
