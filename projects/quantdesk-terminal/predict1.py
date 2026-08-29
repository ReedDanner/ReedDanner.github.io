import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from tkcalendar import DateEntry
import datetime
import threading
import re
import queue
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error, r2_score, mean_absolute_error
from sklearn.preprocessing import MinMaxScaler
import requests
import json
import openai
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import matplotlib.dates as mdates

class StockPredictionApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Stock Price Prediction Professional - Marketstack")
        self.root.geometry("1200x800")
        self.root.minsize(1000, 700)
        
        # Configure style
        self.style = ttk.Style()
        self.style.configure('TFrame', background='#f0f0f0')
        self.style.configure('TLabel', background='#f0f0f0', font=('Calibri', 10))
        self.style.configure('TButton', font=('Calibri', 10))
        self.style.configure('TCombobox', font=('Calibri', 10))
        self.style.configure('TEntry', font=('Calibri', 10))
        
        # Marketstack API key
        self.marketstack_api_key = '13eac196b8c15f8e4341a9627fd87cc8'
        
        # Initialize OpenAI (optional)
        self.openai_api_key = 'sk-proj-SMPV45Zs...'  # Replace with your actual key
        try:
            openai.api_key = self.openai_api_key
        except:
            pass
        
        # Data storage
        self.stock_data = None
        self.valuation_data = None
        self.macro_data = None
        self.news_data = None
        
        # Model storage
        self.models = {
            'Random Forest': None,
            'Ensemble': None,
            'Moving Average': None,
            'Linear Regression': None
        }
        
        # Create GUI
        self.create_widgets()
        
        # Queue for thread-safe updates
        self.console_queue = queue.Queue()
        self.check_console_queue()
    
    def create_widgets(self):
        # Main layout frames
        self.left_frame = ttk.Frame(self.root, width=300, relief=tk.RAISED, borderwidth=2)
        self.left_frame.pack(side=tk.LEFT, fill=tk.Y, expand=False)
        self.left_frame.pack_propagate(False)
        
        self.right_frame = ttk.Frame(self.root)
        self.right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # Right frame layout
        self.console_frame = ttk.Frame(self.right_frame)
        self.console_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        
        self.output_frame = ttk.Frame(self.right_frame, height=200)
        self.output_frame.pack(side=tk.BOTTOM, fill=tk.X, expand=False)
        
        # Left control panel
        self.create_control_panel()
        
        # Console
        self.create_console()
        
        # Output display
        self.create_output_display()
        
        # Matplotlib figure (hidden initially)
        self.chart_frame = ttk.Frame(self.right_frame)
        self.fig = Figure(figsize=(8, 4), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.chart_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        # Add tooltips
        self.create_tooltips()
    
    def create_control_panel(self):
        # Stock symbol
        ttk.Label(self.left_frame, text="Stock Symbol:").pack(pady=(10, 0), padx=5, anchor=tk.W)
        self.symbol_entry = ttk.Entry(self.left_frame)
        self.symbol_entry.insert(0, "AAPL")
        self.symbol_entry.pack(fill=tk.X, padx=5)
        
        # Date selectors
        ttk.Label(self.left_frame, text="Start Date:").pack(pady=(10, 0), padx=5, anchor=tk.W)
        self.start_date = DateEntry(
            self.left_frame,
            date_pattern='yyyy-mm-dd',
            mindate=datetime.date(1980, 1, 1),
            maxdate=datetime.date.today()
        )
        self.start_date.set_date(datetime.date.today() - datetime.timedelta(days=365))
        self.start_date.pack(fill=tk.X, padx=5)
        
        ttk.Label(self.left_frame, text="End Date:").pack(pady=(10, 0), padx=5, anchor=tk.W)
        self.end_date = DateEntry(
            self.left_frame,
            date_pattern='yyyy-mm-dd',
            mindate=datetime.date(1980, 1, 1),
            maxdate=datetime.date.today()
        )
        self.end_date.set_date(datetime.date.today())
        self.end_date.pack(fill=tk.X, padx=5)
        
        # Days to predict
        ttk.Label(self.left_frame, text="Days to Predict:").pack(pady=(10, 0), padx=5, anchor=tk.W)
        self.days_entry = ttk.Entry(self.left_frame)
        self.days_entry.insert(0, "30")
        self.days_entry.pack(fill=tk.X, padx=5)
        
        # OR - Target date (overrides days to predict)
        ttk.Label(self.left_frame, text="OR Target Date:").pack(pady=(10, 0), padx=5, anchor=tk.W)
        self.target_date = DateEntry(
            self.left_frame,
            date_pattern='yyyy-mm-dd',
            mindate=datetime.date.today() + datetime.timedelta(days=1),
            maxdate=datetime.date(2050, 12, 31)
        )
        self.target_date.pack(fill=tk.X, padx=5)
        
        # Model selection
        ttk.Label(self.left_frame, text="Model:").pack(pady=(10, 0), padx=5, anchor=tk.W)
        self.model_var = tk.StringVar()
        self.model_combobox = ttk.Combobox(
            self.left_frame,
            textvariable=self.model_var,
            values=list(self.models.keys()),
            state="readonly"
        )
        self.model_combobox.current(0)
        self.model_combobox.pack(fill=tk.X, padx=5)
        
        # Remove data source selection since we're only using Marketstack
        
        # Checkboxes
        self.valuation_var = tk.IntVar(value=1)
        self.valuation_cb = ttk.Checkbutton(
            self.left_frame,
            text="Include Valuation Metrics",
            variable=self.valuation_var
        )
        self.valuation_cb.pack(pady=(10, 0), padx=5, anchor=tk.W)
        
        self.macro_var = tk.IntVar(value=1)
        self.macro_cb = ttk.Checkbutton(
            self.left_frame,
            text="Include Macroeconomic Data",
            variable=self.macro_var
        )
        self.macro_cb.pack(pady=(5, 0), padx=5, anchor=tk.W)
        
        self.news_var = tk.IntVar(value=1)
        self.news_cb = ttk.Checkbutton(
            self.left_frame,
            text="Include News Sentiment",
            variable=self.news_var
        )
        self.news_cb.pack(pady=(5, 0), padx=5, anchor=tk.W)
        
        self.backtest_var = tk.IntVar(value=1)
        self.backtest_cb = ttk.Checkbutton(
            self.left_frame,
            text="Run Backtest",
            variable=self.backtest_var
        )
        self.backtest_cb.pack(pady=(5, 0), padx=5, anchor=tk.W)
        
        self.openai_var = tk.IntVar(value=0)  # Disabled by default
        self.openai_cb = ttk.Checkbutton(
            self.left_frame,
            text="Use OpenAI for Price Estimation",
            variable=self.openai_var
        )
        self.openai_cb.pack(pady=(5, 0), padx=5, anchor=tk.W)
        
        # Buttons
        self.fetch_btn = ttk.Button(
            self.left_frame,
            text="Fetch Data (Marketstack)",
            command=self.start_fetch_data_thread
        )
        self.fetch_btn.pack(pady=(20, 5), padx=5, fill=tk.X)
        
        self.predict_btn = ttk.Button(
            self.left_frame,
            text="Predict",
            command=self.start_predict_thread
        )
        self.predict_btn.pack(pady=5, padx=5, fill=tk.X)
        
        self.reset_btn = ttk.Button(
            self.left_frame,
            text="Reset",
            command=self.reset
        )
        self.reset_btn.pack(pady=5, padx=5, fill=tk.X)
        
        self.export_btn = ttk.Button(
            self.left_frame,
            text="Export",
            command=self.export_data
        )
        self.export_btn.pack(pady=5, padx=5, fill=tk.X)
    
    def create_console(self):
        self.console = scrolledtext.ScrolledText(
            self.console_frame,
            wrap=tk.WORD,
            width=60,
            height=20,
            font=('Consolas', 10)
        )
        self.console.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.console.insert(tk.END, "Console initialized. Ready to fetch data from Marketstack...\n")
    
    def create_output_display(self):
        self.output_text = tk.Text(
            self.output_frame,
            wrap=tk.WORD,
            width=60,
            height=10,
            font=('Calibri', 12, 'bold'),
            relief=tk.SUNKEN,
            borderwidth=2
        )
        self.output_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Configure tags for styling
        self.output_text.tag_configure('title', font=('Calibri', 14, 'bold'), justify='center')
        self.output_text.tag_configure('label', font=('Calibri', 11, 'bold'))
        self.output_text.tag_configure('value', font=('Calibri', 11))
        self.output_text.tag_configure('center', justify='center')
        
        # Initial placeholder text
        self.output_text.insert(tk.END, "\n" * 3 + " " * 20 + "Predictions will appear here\n", 'title')
    
    def create_tooltips(self):
        # Create tooltip functionality
        pass  # Implementation would go here in a full version
    
    def log_to_console(self, message):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] {message}\n"
        self.console_queue.put(formatted_message)
    
    def check_console_queue(self):
        while not self.console_queue.empty():
            message = self.console_queue.get()
            self.console.insert(tk.END, message)
            self.console.see(tk.END)
        self.root.after(100, self.check_console_queue)
    
    def start_fetch_data_thread(self):
        self.fetch_btn.config(state=tk.DISABLED)
        thread = threading.Thread(target=self.fetch_data, daemon=True)
        thread.start()
    
    def fetch_data(self):
        symbol = self.symbol_entry.get().upper()
        start_date = self.start_date.get_date()
        end_date = self.end_date.get_date()
        
        # Validate inputs
        if not symbol:
            self.console_queue.put("Error: Please enter a stock symbol")
            self.fetch_btn.config(state=tk.NORMAL)
            return
        
        if start_date > end_date:
            self.console_queue.put("Error: Start date must be before end date")
            self.fetch_btn.config(state=tk.NORMAL)
            return
        
        try:
            # Fetch data from Marketstack only
            success = self.fetch_marketstack(symbol, start_date, end_date)
            
            if success:
                # Fetch additional data based on checkboxes
                if self.valuation_var.get():
                    self.fetch_valuation_data(symbol)
                
                if self.macro_var.get():
                    self.fetch_macro_data()
                
                if self.news_var.get():
                    self.fetch_news_data(symbol)
                
                self.log_to_console(f"Successfully fetched data for {symbol}")
                self.log_to_console(f"Data range: {self.stock_data.index[0].date()} to {self.stock_data.index[-1].date()}")
                self.log_to_console(f"Total records: {len(self.stock_data)}")
                
                # Enable predict button
                self.predict_btn.config(state=tk.NORMAL)
            else:
                self.log_to_console("Error: Failed to fetch data from Marketstack")
        
        except Exception as e:
            self.log_to_console(f"Error fetching data: {str(e)}")
        
        self.fetch_btn.config(state=tk.NORMAL)
    
    def fetch_marketstack(self, symbol, start_date, end_date):
        self.log_to_console(f"Fetching from Marketstack for {symbol}...")
        
        # Format dates for API
        start_str = start_date.strftime('%Y-%m-%d')
        end_str = end_date.strftime('%Y-%m-%d')
        
        # Marketstack API endpoint with date range and limit
        url = f"http://api.marketstack.com/v1/eod"
        params = {
            'access_key': self.marketstack_api_key,
            'symbols': symbol,
            'date_from': start_str,
            'date_to': end_str,
            'limit': 1000  # Maximum records per request
        }
        
        try:
            self.log_to_console(f"Requesting data from {start_str} to {end_str}")
            response = requests.get(url, params=params)
            
            if response.status_code != 200:
                self.log_to_console(f"HTTP Error: {response.status_code}")
                return False
            
            data = response.json()
            
            if 'error' in data:
                self.log_to_console(f"Marketstack API error: {data['error']['message']}")
                return False
            
            if 'data' not in data or not data['data']:
                self.log_to_console(f"No data found for symbol {symbol}")
                return False
            
            # Process data
            df = pd.DataFrame(data['data'])
            
            # Convert date column to datetime and set as index
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
            
            # Select relevant columns and ensure they're numeric
            columns_to_keep = ['open', 'high', 'low', 'close', 'volume']
            if 'adj_close' in df.columns:
                columns_to_keep.append('adj_close')
            
            df = df[columns_to_keep]
            
            # Convert to numeric, handling any non-numeric values
            for col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # Remove any rows with NaN values
            df = df.dropna()
            
            # Sort by date (oldest first)
            df = df.sort_index()
            
            self.stock_data = df
            
            self.log_to_console(f"Successfully processed {len(df)} records")
            self.log_to_console(f"Columns available: {list(df.columns)}")
            self.log_to_console(f"Latest close price: ${df['close'].iloc[-1]:.2f}")
            
            return True
        
        except requests.exceptions.RequestException as e:
            self.log_to_console(f"Network error: {str(e)}")
            return False
        except Exception as e:
            self.log_to_console(f"Marketstack error: {str(e)}")
            return False
    
    def fetch_valuation_data(self, symbol):
        self.log_to_console(f"Fetching valuation data for {symbol}...")
        
        # Placeholder - in a real app we'd implement API calls to get financials
        # You could integrate with other APIs like Financial Modeling Prep, IEX Cloud, etc.
        self.valuation_data = {
            'EPS': 5.20,
            'PE Ratio': 28.5,
            'PEG Ratio': 1.8,
            'ROE': 0.45,
            'ROA': 0.18,
            'Net Income': 94_680_000_000,
            'Debt/Equity': 1.45,
            'DCF Value': 175.00
        }
        self.log_to_console("Valuation data loaded (placeholder values)")
    
    def fetch_macro_data(self):
        self.log_to_console("Fetching macroeconomic data...")
        
        # Placeholder - in a real app we'd implement API calls to FRED or other sources
        self.macro_data = {
            'Fed Funds Rate': 0.08,
            'CPI Inflation': 3.2,
            'Unemployment Rate': 3.6
        }
        self.log_to_console("Macroeconomic data loaded (placeholder values)")
    
    def fetch_news_data(self, symbol):
        self.log_to_console(f"Fetching news data for {symbol}...")
        
        # Placeholder - in a real app we'd implement NewsAPI calls or other news sources
        self.news_data = [
            f"{symbol} announces breakthrough in technology",
            f"New {symbol} product sales exceed expectations",
            "Regulatory concerns weigh on tech stocks",
            f"{symbol} partners with major company",
            "Supply chain issues resolved, says CEO"
        ]
        self.log_to_console("News sentiment data loaded (placeholder values)")
    
    def start_predict_thread(self):
        self.predict_btn.config(state=tk.DISABLED)
        thread = threading.Thread(target=self.run_prediction, daemon=True)
        thread.start()
    
    def run_prediction(self):
        symbol = self.symbol_entry.get().upper()
        model_name = self.model_var.get()
        
        try:
            # Determine prediction timeframe
            days_to_predict = int(self.days_entry.get())
            
            # If target date is specified, override days_to_predict
            try:
                target_date = self.target_date.get_date()
                last_date = self.stock_data.index[-1].date()
                if target_date > last_date:
                    calculated_days = (target_date - last_date).days
                    days_to_predict = calculated_days
                    self.log_to_console(f"Calculated {days_to_predict} days to reach target date {target_date}")
            except:
                pass
            
            # Prepare data for ML
            data = self.stock_data.copy()
            
            # Use adjusted close if available, otherwise close
            if 'adj_close' in data.columns:
                prices = data['adj_close'].values
                self.log_to_console("Using adjusted close prices for prediction")
            else:
                prices = data['close'].values
                self.log_to_console("Using close prices for prediction")
            
            # Prepare feature matrix
            X = []
            y = []
            window_size = min(30, len(prices) // 4)  # Use last 30 days or 1/4 of data, whichever is smaller
            
            self.log_to_console(f"Using window size of {window_size} days")
            
            for i in range(len(prices) - window_size - 1):
                X.append(prices[i:i + window_size])
                y.append(prices[i + window_size])
            
            X = np.array(X)
            y = np.array(y)
            
            if len(X) < 10:
                self.log_to_console("Error: Not enough data for prediction. Need at least 40 data points.")
                self.predict_btn.config(state=tk.NORMAL)
                return
            
            # Split data
            split = max(1, int(0.8 * len(X)))
            X_train, X_test = X[:split], X[split:]
            y_train, y_test = y[:split], y[split:]
            
            # Train selected model
            self.log_to_console(f"Training {model_name} model with {len(X_train)} samples...")
            
            if model_name == "Random Forest":
                model = RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1)
                model.fit(X_train, y_train)
                self.models['Random Forest'] = model
            elif model_name == "Ensemble":
                rf = RandomForestRegressor(n_estimators=50, random_state=42, n_jobs=-1)
                gb = GradientBoostingRegressor(n_estimators=50, random_state=42)
                rf.fit(X_train, y_train)
                gb.fit(X_train, y_train)
                self.models['Ensemble'] = (rf, gb)
                model = None  # Ensemble is special case
            elif model_name == "Moving Average":
                self.models['Moving Average'] = "SMA"  # Just a marker
                model = None  # Moving average doesn't need training
            elif model_name == "Linear Regression":
                model = LinearRegression()
                model.fit(X_train, y_train)
                self.models['Linear Regression'] = model
            
            # Make predictions
            self.log_to_console("Making predictions...")
            predictions = []
            
            if model_name == "Random Forest" or model_name == "Linear Regression":
                # Use trained model to predict next 'days_to_predict' days
                current_window = prices[-window_size:].reshape(1, -1)
                for day in range(days_to_predict):
                    next_pred = model.predict(current_window)[0]
                    predictions.append(next_pred)
                    # Update window by dropping first element and adding new prediction
                    current_window = np.append(current_window[:, 1:], next_pred).reshape(1, -1)
                    if (day + 1) % 10 == 0:
                        self.log_to_console(f"Predicted day {day + 1}/{days_to_predict}")
                
            elif model_name == "Ensemble":
                # Average predictions from RF and GB
                rf, gb = self.models['Ensemble']
                current_window = prices[-window_size:].reshape(1, -1)
                for day in range(days_to_predict):
                    rf_pred = rf.predict(current_window)[0]
                    gb_pred = gb.predict(current_window)[0]
                    next_pred = (rf_pred + gb_pred) / 2
                    predictions.append(next_pred)
                    current_window = np.append(current_window[:, 1:], next_pred).reshape(1, -1)
                    if (day + 1) % 10 == 0:
                        self.log_to_console(f"Predicted day {day + 1}/{days_to_predict}")
                
            elif model_name == "Moving Average":
                # Simple moving average forecast
                sma = pd.Series(prices).rolling(window=window_size).mean().values[-1]
                predictions = [sma] * days_to_predict
            
            # Calculate target date
            last_date = self.stock_data.index[-1]
            target_date = last_date + pd.Timedelta(days=days_to_predict)
            
            # Display predictions
            self.display_predictions(symbol, model_name, predictions[-1], target_date, predictions)
            
            # If OpenAI is enabled, get AI estimate
            if self.openai_var.get():
                self.get_openai_estimate(symbol, target_date)
            
            # If backtest is enabled, run it
            if self.backtest_var.get() and len(X_test) > 0:
                self.run_backtest(X_test, y_test, model_name)
            
            # Show chart
            self.show_chart(prices, predictions, days_to_predict)
        
        except Exception as e:
            self.log_to_console(f"Error during prediction: {str(e)}")
        
        self.predict_btn.config(state=tk.NORMAL)
    
    def display_predictions(self, symbol, model_name, final_prediction, target_date, all_predictions):
        self.output_text.delete(1.0, tk.END)
        
        # Format the target date
        formatted_date = target_date.strftime("%Y-%m-%d")
        current_price = self.stock_data['close'].iloc[-1]
        
        # Calculate price change
        price_change = final_prediction - current_price
        price_change_pct = (price_change / current_price) * 100
        
        # Add title
        self.output_text.insert(tk.END, f"Stock Price Prediction for {symbol}\n", 'title')
        self.output_text.insert(tk.END, "\n", 'center')
        
        # Add current price
        self.output_text.insert(tk.END, "Current Price: ", 'label')
        self.output_text.insert(tk.END, f"${current_price:.2f}\n", 'value')
        
        # Add model prediction
        self.output_text.insert(tk.END, "Predicted Price: ", 'label')
        self.output_text.insert(tk.END, f"${final_prediction:.2f}\n", 'value')
        
        # Add price change
        change_color = 'green' if price_change > 0 else 'red'
        self.output_text.insert(tk.END, "Expected Change: ", 'label')
        self.output_text.insert(tk.END, f"${price_change:+.2f} ({price_change_pct:+.1f}%)\n", 'value')
        
        # Add model used
        self.output_text.insert(tk.END, "Model Used: ", 'label')
        self.output_text.insert(tk.END, f"{model_name}\n", 'value')
        
        # Add target date
        self.output_text.insert(tk.END, "Target Date: ", 'label')
        self.output_text.insert(tk.END, f"{formatted_date}\n", 'value')
        
        # Add prediction range
        if len(all_predictions) > 1:
            min_pred = min(all_predictions)
            max_pred = max(all_predictions)
            self.output_text.insert(tk.END, "Price Range: ", 'label')
            self.output_text.insert(tk.END, f"${min_pred:.2f} - ${max_pred:.2f}\n", 'value')
        
        # Add confidence (simplified for this example)
        confidence = "High" if model_name in ["Ensemble", "Random Forest"] else "Moderate"
        self.output_text.insert(tk.END, "Confidence: ", 'label')
        self.output_text.insert(tk.END, f"{confidence}\n", 'value')
        
        # Add data source
        self.output_text.insert(tk.END, "Data Source: ", 'label')
        self.output_text.insert(tk.END, "Marketstack API\n", 'value')
    
    def get_openai_estimate(self, symbol, target_date):
        self.log_to_console("Getting AI-powered estimate from OpenAI...")
        
        # Prepare the prompt
        current_price = self.stock_data['close'].iloc[-1]
        prompt = f"""
        Based on the following financial data for {symbol}, what is your expected price for {symbol} on {target_date.strftime('%Y-%m-%d')}?

        Current Price: ${current_price:.2f}
        Recent Price Trend: {self.stock_data['close'].tail(5).tolist()}
        Valuation Metrics: {json.dumps(self.valuation_data, indent=2) if self.valuation_data else 'Not available'}
        Macroeconomic Data: {json.dumps(self.macro_data, indent=2) if self.macro_data else 'Not available'}
        Recent News Headlines: {json.dumps(self.news_data, indent=2) if self.news_data else 'Not available'}

        Please provide:
        1. Your price estimate
        2. A brief rationale for your estimate (100 words max)
        """
        
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",  # Using gpt-3.5-turbo as it's more accessible
                messages=[
                    {"role": "system", "content": "You are a financial analyst specializing in stock price prediction."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=150
            )
            
            # Parse the response
            ai_response = response.choices[0].message.content
            self.log_to_console(f"OpenAI response received")
            
            # Extract the price estimate (simple pattern matching)
            price_matches = re.findall(r'\$\d+\.?\d*', ai_response)
            if price_matches:
                ai_price = float(price_matches[0].replace('$', ''))
                
                # Add to output display
                self.output_text.insert(tk.END, "\nAI Estimate: ", 'label')
                self.output_text.insert(tk.END, f"${ai_price:.2f}\n", 'value')
                
                # Add rationale
                self.output_text.insert(tk.END, "\nAI Rationale:\n", 'label')
                self.output_text.insert(tk.END, f"{ai_response}\n", 'value')
            else:
                self.log_to_console("Could not parse price from OpenAI response")
                self.output_text.insert(tk.END, "\nAI Analysis:\n", 'label')
                self.output_text.insert(tk.END, f"{ai_response}\n", 'value')
                
        except Exception as e:
            self.log_to_console(f"Error getting OpenAI estimate: {str(e)}")
    
    def run_backtest(self, X_test, y_test, model_name):
        self.log_to_console("Running backtest...")
        
        model = self.models.get(model_name, None)
        test_pred = None
        
        try:
            if model_name == "Random Forest" or model_name == "Linear Regression":
                test_pred = model.predict(X_test)
                
            elif model_name == "Ensemble":
                rf, gb = model
                rf_pred = rf.predict(X_test)
                gb_pred = gb.predict(X_test)
                test_pred = (rf_pred + gb_pred) / 2
                
            elif model_name == "Moving Average":
                # For MA, calculate mean of test values
                test_pred = np.full_like(y_test, np.mean(y_test))
            
            if test_pred is not None and len(test_pred) > 0:
                rmse = np.sqrt(mean_squared_error(y_test, test_pred))
                r2 = r2_score(y_test, test_pred)
                mae = mean_absolute_error(y_test, test_pred)
                
                # Calculate percentage error
                mape = np.mean(np.abs((y_test - test_pred) / y_test)) * 100
                
                self.log_to_console(f"\nBacktest Results ({model_name}):")
                self.log_to_console(f"RMSE: ${rmse:.4f}")
                self.log_to_console(f"R²: {r2:.4f}")
                self.log_to_console(f"MAE: ${mae:.4f}")
                self.log_to_console(f"MAPE: {mape:.2f}%")
                
                # Add backtest results to output
                self.output_text.insert(tk.END, f"\nBacktest RMSE: ", 'label')
                self.output_text.insert(tk.END, f"${rmse:.2f}\n", 'value')
                self.output_text.insert(tk.END, f"Backtest R²: ", 'label')
                self.output_text.insert(tk.END, f"{r2:.3f}\n", 'value')
            else:
                self.log_to_console("Could not run backtest - insufficient test data")
                
        except Exception as e:
            self.log_to_console(f"Error in backtest: {str(e)}")
    
    def show_chart(self, historical_prices, predictions, days_to_predict):
        try:
            self.chart_frame.pack(fill=tk.BOTH, expand=True)
            
            # Clear previous plot
            self.ax.clear()
            
            # Plot historical prices
            historical_dates = self.stock_data.index
            self.ax.plot(historical_dates, historical_prices, label='Historical Prices', color='blue', linewidth=2)
            
            # Plot predictions
            last_date = self.stock_data.index[-1]
            pred_dates = pd.date_range(
                start=last_date + pd.Timedelta(days=1),
                periods=days_to_predict,
                freq='D'
            )
            
            # Connect last historical point to first prediction
            connection_dates = [last_date, pred_dates[0]]
            connection_prices = [historical_prices[-1], predictions[0]]
            self.ax.plot(connection_dates, connection_prices, color='red', linestyle='--', alpha=0.7)
            
            # Plot predictions
            self.ax.plot(pred_dates, predictions, label='Predicted Prices', color='red', linestyle='--', linewidth=2)
            
            # Add markers for key points
            self.ax.scatter([last_date], [historical_prices[-1]], color='blue', s=50, zorder=5)
            self.ax.scatter([pred_dates[-1]], [predictions[-1]], color='red', s=50, zorder=5)
            
            # Formatting
            symbol = self.symbol_entry.get().upper()
            self.ax.set_title(f"{symbol} Price Prediction - Marketstack Data", fontsize=14, fontweight='bold')
            self.ax.set_xlabel("Date", fontsize=12)
            self.ax.set_ylabel("Price ($)", fontsize=12)
            self.ax.legend(fontsize=10)
            self.ax.grid(True, alpha=0.3)
            
            # Format x-axis dates
            self.ax.xaxis.set_major_locator(mdates.AutoDateLocator())
            self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
            self.fig.autofmt_xdate()
            
            # Add price annotations
            current_price = historical_prices[-1]
            predicted_price = predictions[-1]
            
            self.ax.annotate(f'Current: ${current_price:.2f}', 
                           xy=(last_date, current_price), 
                           xytext=(10, 10), textcoords='offset points',
                           bbox=dict(boxstyle='round,pad=0.3', facecolor='blue', alpha=0.7),
                           fontsize=9, color='white')
            
            self.ax.annotate(f'Predicted: ${predicted_price:.2f}', 
                           xy=(pred_dates[-1], predicted_price), 
                           xytext=(10, -20), textcoords='offset points',
                           bbox=dict(boxstyle='round,pad=0.3', facecolor='red', alpha=0.7),
                           fontsize=9, color='white')
            
            # Adjust layout
            self.fig.tight_layout()
            self.canvas.draw()
            
            self.log_to_console("Chart updated successfully")
            
        except Exception as e:
            self.log_to_console(f"Error creating chart: {str(e)}")
    
    def reset(self):
        # Reset inputs to defaults
        self.symbol_entry.delete(0, tk.END)
        self.symbol_entry.insert(0, "AAPL")
        
        self.start_date.set_date(datetime.date.today() - datetime.timedelta(days=365))
        self.end_date.set_date(datetime.date.today())
        
        self.days_entry.delete(0, tk.END)
        self.days_entry.insert(0, "30")
        
        self.model_combobox.current(0)
        
        # Reset checkboxes
        self.valuation_var.set(1)
        self.macro_var.set(1)
        self.news_var.set(1)
        self.backtest_var.set(1)
        self.openai_var.set(0)
        
        # Clear data
        self.stock_data = None
        self.valuation_data = None
        self.macro_data = None
        self.news_data = None
        
        # Reset models
        for key in self.models:
            self.models[key] = None
        
        # Clear outputs
        self.output_text.delete(1.0, tk.END)
        self.output_text.insert(tk.END, "\n" * 3 + " " * 20 + "Predictions will appear here\n", 'title')
        
        # Clear chart if visible
        try:
            self.chart_frame.pack_forget()
            self.ax.clear()
            self.canvas.draw()
        except:
            pass
        
        # Clear console
        self.console.delete(1.0, tk.END)
        self.log_to_console("Application reset. Ready for new prediction...")
        
        # Disable predict button until new data is fetched
        self.predict_btn.config(state=tk.DISABLED)
    
    def export_data(self):
        """Export predictions and data to files"""
        try:
            if self.stock_data is None:
                messagebox.showwarning("No Data", "Please fetch data first before exporting.")
                return
            
            symbol = self.symbol_entry.get().upper()
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Export stock data to CSV
            filename = f"{symbol}_data_{timestamp}.csv"
            self.stock_data.to_csv(filename)
            self.log_to_console(f"Stock data exported to {filename}")
            
            # Export predictions if available
            predictions_text = self.output_text.get(1.0, tk.END)
            if "Predicted Price:" in predictions_text:
                pred_filename = f"{symbol}_predictions_{timestamp}.txt"
                with open(pred_filename, 'w') as f:
                    f.write(f"Stock Prediction Report - {symbol}\n")
                    f.write(f"Generated on: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"Data Source: Marketstack API\n")
                    f.write("="*50 + "\n\n")
                    f.write(predictions_text)
                self.log_to_console(f"Predictions exported to {pred_filename}")
            
            messagebox.showinfo("Export Complete", f"Data exported successfully!\nFiles saved with timestamp: {timestamp}")
            
        except Exception as e:
            self.log_to_console(f"Error exporting data: {str(e)}")
            messagebox.showerror("Export Error", f"Failed to export data: {str(e)}")

# Run the application
if __name__ == "__main__":
    root = tk.Tk()
    app = StockPredictionApp(root)
    root.mainloop()
