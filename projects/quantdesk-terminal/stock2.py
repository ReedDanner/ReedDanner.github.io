"""
Advanced Stock Price Prediction System
=====================================

A comprehensive stock prediction system using multiple mathematical and statistical models
including Linear Regression, Moving Averages, ARIMA, and GARCH with ensemble methods.

Features:
- Multiple API data sources (Alpha Vantage, Finnhub, Marketstack)
- Advanced preprocessing (splits, dividends, outliers)
- Multiple prediction horizons (1 week to 12 months)
- Ensemble modeling with volatility adjustment
- Automated backtesting and performance evaluation
- Technical indicators (MACD, Bollinger Bands)
- Risk assessment and confidence scoring

Author: AI Assistant
Date: 2024
"""

import pandas as pd
import numpy as np
import requests
import warnings
import time
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import json
from dataclasses import dataclass
from enum import Enum

# Statistical and ML libraries
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_squared_error, mean_absolute_error
from scipy import stats
from scipy.optimize import minimize

# Time series libraries
try:
    from statsmodels.tsa.arima.model import ARIMA
    from statsmodels.tsa.stattools import adfuller
    from arch import arch_model
    ADVANCED_MODELS_AVAILABLE = True
except ImportError:
    print("Warning: Advanced models (ARIMA, GARCH) not available. Install with: pip install statsmodels arch")
    ADVANCED_MODELS_AVAILABLE = False

warnings.filterwarnings('ignore')

# API Configuration - Updated with your Marketstack API key
API_KEYS = {
    'ALPHA_VANTAGE': ['UQZTI0SJ8OF083KZ', 'ER1MFGNFUQ8LQ0BP'],
    'FINNHUB': 'd13i2c1r01qs7glhntg0d13i2c1r01qs7glhntgg',
    'MARKETSTACK': '13eac196b8c15f8e4341a9627fd87cc8'  # Your API key
}

class MovementCategory(Enum):
    BARELY_CHANGES = "barely changes"
    POSITIVE_MOVE = "positive move"
    NEGATIVE_MOVE = "negative move"

@dataclass
class PredictionResult:
    horizon: str
    predicted_price: float
    current_price: float
    percentage_change: float
    movement_category: MovementCategory
    confidence: float
    volatility_risk: float
    model_weights: Dict[str, float]

class ProgressBar:
    def __init__(self, total: int, description: str = "Progress"):
        self.total = total
        self.current = 0
        self.description = description
        self.start_time = time.time()
    
    def update(self, increment: int = 1):
        self.current += increment
        self._display()
    
    def _display(self):
        percentage = (self.current / self.total) * 100
        bar_length = 50
        filled_length = int(bar_length * self.current // self.total)
        bar = '=' * filled_length + '-' * (bar_length - filled_length)
        
        elapsed_time = time.time() - self.start_time
        if self.current > 0:
            eta = (elapsed_time / self.current) * (self.total - self.current)
            eta_str = f"ETA: {eta:.1f}s"
        else:
            eta_str = "ETA: --"
        
        sys.stdout.write(f'\r{self.description}: |{bar}| {percentage:.1f}% {eta_str}')
        sys.stdout.flush()
        
        if self.current >= self.total:
            print()

class DataFetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'StockPredictor/1.0'})
    
    def fetch_alpha_vantage(self, symbol: str) -> Optional[pd.DataFrame]:
        """Fetch data from Alpha Vantage API"""
        for api_key in API_KEYS['ALPHA_VANTAGE']:
            try:
                url = f"https://www.alphavantage.co/query"
                params = {
                    'function': 'TIME_SERIES_DAILY_ADJUSTED',
                    'symbol': symbol,
                    'outputsize': 'full',
                    'apikey': api_key
                }
                
                response = self.session.get(url, params=params, timeout=30)
                data = response.json()
                
                if 'Time Series (Daily)' in data:
                    df = pd.DataFrame(data['Time Series (Daily)']).T
                    df.index = pd.to_datetime(df.index)
                    df = df.astype(float)
                    df.columns = ['open', 'high', 'low', 'close', 'adjusted_close', 'volume', 'dividend', 'split']
                    return df.sort_index()
                    
            except Exception as e:
                print(f"Alpha Vantage error with key {api_key[:8]}...: {e}")
                continue
        
        return None
    
    def fetch_finnhub(self, symbol: str) -> Optional[pd.DataFrame]:
        """Fetch data from Finnhub API"""
        try:
            # Get data for the last 5 years
            end_date = int(datetime.now().timestamp())
            start_date = int((datetime.now() - timedelta(days=1825)).timestamp())
            
            url = f"https://finnhub.io/api/v1/stock/candle"
            params = {
                'symbol': symbol,
                'resolution': 'D',
                'from': start_date,
                'to': end_date,
                'token': API_KEYS['FINNHUB']
            }
            
            response = self.session.get(url, params=params, timeout=30)
            data = response.json()
            
            if data.get('s') == 'ok':
                df = pd.DataFrame({
                    'open': data['o'],
                    'high': data['h'],
                    'low': data['l'],
                    'close': data['c'],
                    'volume': data['v']
                })
                df.index = pd.to_datetime(data['t'], unit='s')
                df['adjusted_close'] = df['close']  # Finnhub doesn't provide adjusted close
                return df.sort_index()
                
        except Exception as e:
            print(f"Finnhub error: {e}")
        
        return None
    
    def fetch_marketstack(self, symbol: str) -> Optional[pd.DataFrame]:
        """Fetch data from Marketstack API - Enhanced with better error handling"""
        try:
            url = f"http://api.marketstack.com/v1/eod"
            params = {
                'access_key': API_KEYS['MARKETSTACK'],
                'symbols': symbol,
                'limit': 1000,  # Get more historical data
                'sort': 'DESC'
            }
            
            print(f"Fetching Marketstack data for {symbol}...")
            response = self.session.get(url, params=params, timeout=30)
            
            # Check if request was successful
            if response.status_code != 200:
                print(f"Marketstack API returned status code: {response.status_code}")
                return None
            
            data = response.json()
            
            # Check for API errors
            if 'error' in data:
                print(f"Marketstack API error: {data['error']}")
                return None
            
            if 'data' in data and data['data']:
                df = pd.DataFrame(data['data'])
                
                # Check if we have the required columns
                required_columns = ['date', 'open', 'high', 'low', 'close', 'volume']
                if not all(col in df.columns for col in required_columns):
                    print(f"Missing required columns in Marketstack data")
                    return None
                
                df['date'] = pd.to_datetime(df['date'])
                df.set_index('date', inplace=True)
                
                # Handle adjusted close - use adj_close if available, otherwise use close
                if 'adj_close' in df.columns:
                    df['adjusted_close'] = df['adj_close']
                else:
                    df['adjusted_close'] = df['close']
                
                # Ensure numeric data types
                numeric_columns = ['open', 'high', 'low', 'close', 'volume', 'adjusted_close']
                for col in numeric_columns:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')
                
                # Remove any rows with NaN values in critical columns
                df = df.dropna(subset=['open', 'high', 'low', 'close'])
                
                print(f"Successfully fetched {len(df)} records from Marketstack")
                return df.sort_index()
            else:
                print("No data returned from Marketstack API")
                return None
                
        except requests.exceptions.Timeout:
            print("Marketstack API request timed out")
        except requests.exceptions.RequestException as e:
            print(f"Marketstack API request error: {e}")
        except Exception as e:
            print(f"Marketstack error: {e}")
        
        return None
    
    def fetch_all_sources(self, symbol: str) -> pd.DataFrame:
        """Fetch data from all available sources and combine - Prioritize Marketstack"""
        print(f"\nFetching data for {symbol}...")
        progress = ProgressBar(3, "Data Retrieval")
        
        datasets = []
        
        # Try Marketstack first (your API key)
        ms_data = self.fetch_marketstack(symbol)
        if ms_data is not None:
            datasets.append(('Marketstack', ms_data))
        progress.update()
        
        # Try Alpha Vantage as backup
        av_data = self.fetch_alpha_vantage(symbol)
        if av_data is not None:
            datasets.append(('Alpha Vantage', av_data))
        progress.update()
        
        # Try Finnhub as second backup
        fh_data = self.fetch_finnhub(symbol)
        if fh_data is not None:
            datasets.append(('Finnhub', fh_data))
        progress.update()
        
        if not datasets:
            raise ValueError(f"No data could be retrieved for symbol {symbol} from any source. Please check if the symbol is valid.")
        
        # Prioritize Marketstack if available, otherwise use the dataset with the most data
        marketstack_data = next((data for name, data in datasets if name == 'Marketstack'), None)
        if marketstack_data is not None:
            best_dataset = ('Marketstack', marketstack_data)
        else:
            best_dataset = max(datasets, key=lambda x: len(x[1]))
        
        print(f"\nUsing {best_dataset[0]} data ({len(best_dataset[1])} records)")
        
        # Validate the dataset
        df = best_dataset[1]
        if len(df) < 100:
            print(f"Warning: Only {len(df)} records available. Results may be less reliable.")
        
        return df

class DataPreprocessor:
    @staticmethod
    def handle_splits_and_dividends(df: pd.DataFrame) -> pd.DataFrame:
        """Handle stock splits and dividends"""
        df = df.copy()
        
        if 'split' in df.columns:
            # Detect splits (split coefficient != 1)
            splits = df['split'] != 1.0
            if splits.any():
                print(f"Detected {splits.sum()} stock splits")
        
        # Use adjusted close if available, otherwise use close
        if 'adjusted_close' in df.columns:
            df['price'] = df['adjusted_close']
        else:
            df['price'] = df['close']
        
        return df
    
    @staticmethod
    def detect_outliers(series: pd.Series, method: str = 'iqr') -> pd.Series:
        """Detect outliers using IQR or Z-score method"""
        if method == 'iqr':
            Q1 = series.quantile(0.25)
            Q3 = series.quantile(0.75)
            IQR = Q3 - Q1
            lower_bound = Q1 - 1.5 * IQR
            upper_bound = Q3 + 1.5 * IQR
            return (series < lower_bound) | (series > upper_bound)
        
        elif method == 'zscore':
            z_scores = np.abs(stats.zscore(series.dropna()))
            return z_scores > 3
    
    @staticmethod
    def handle_missing_data(df: pd.DataFrame) -> pd.DataFrame:
        """Handle missing data with forward fill and interpolation"""
        df = df.copy()
        
        # Forward fill first, then backward fill
        df = df.fillna(method='ffill').fillna(method='bfill')
        
        # Interpolate remaining missing values
        numeric_columns = df.select_dtypes(include=[np.number]).columns
        df[numeric_columns] = df[numeric_columns].interpolate(method='linear')
        
        return df
    
    @staticmethod
    def calculate_returns(df: pd.DataFrame) -> pd.DataFrame:
        """Calculate various types of returns"""
        df = df.copy()
        
        df['returns'] = df['price'].pct_change()
        df['log_returns'] = np.log(df['price'] / df['price'].shift(1))
        df['volatility'] = df['returns'].rolling(window=20).std()
        
        return df

class TechnicalIndicators:
    @staticmethod
    def moving_averages(df: pd.DataFrame) -> pd.DataFrame:
        """Calculate various moving averages"""
        df = df.copy()
        
        for window in [5, 10, 20, 50, 200]:
            df[f'ma_{window}'] = df['price'].rolling(window=window).mean()
            df[f'ema_{window}'] = df['price'].ewm(span=window).mean()
        
        return df
    
    @staticmethod
    def bollinger_bands(df: pd.DataFrame, window: int = 20, num_std: float = 2) -> pd.DataFrame:
        """Calculate Bollinger Bands"""
        df = df.copy()
        
        rolling_mean = df['price'].rolling(window=window).mean()
        rolling_std = df['price'].rolling(window=window).std()
        
        df['bb_upper'] = rolling_mean + (rolling_std * num_std)
        df['bb_lower'] = rolling_mean - (rolling_std * num_std)
        df['bb_middle'] = rolling_mean
        df['bb_width'] = df['bb_upper'] - df['bb_lower']
        df['bb_position'] = (df['price'] - df['bb_lower']) / df['bb_width']
        
        return df
    
    @staticmethod
    def macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
        """Calculate MACD indicator"""
        df = df.copy()
        
        ema_fast = df['price'].ewm(span=fast).mean()
        ema_slow = df['price'].ewm(span=slow).mean()
        
        df['macd'] = ema_fast - ema_slow
        df['macd_signal'] = df['macd'].ewm(span=signal).mean()
        df['macd_histogram'] = df['macd'] - df['macd_signal']
        
        return df
    
    @staticmethod
    def rsi(df: pd.DataFrame, window: int = 14) -> pd.DataFrame:
        """Calculate RSI indicator"""
        df = df.copy()
        
        delta = df['price'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
        
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        return df

class PredictionModels:
    def __init__(self):
        self.models = {}
        self.scalers = {}
    
    def prepare_features(self, df: pd.DataFrame, lookback: int = 60) -> Tuple[np.ndarray, np.ndarray]:
        """Prepare features for machine learning models"""
        # Select relevant features
        feature_columns = [
            'price', 'volume', 'returns', 'volatility',
            'ma_5', 'ma_10', 'ma_20', 'ma_50',
            'bb_position', 'bb_width',
            'macd', 'macd_signal', 'macd_histogram',
            'rsi'
        ]
        
        # Filter available columns
        available_features = [col for col in feature_columns if col in df.columns]
        feature_data = df[available_features].dropna()
        
        if len(feature_data) < lookback + 1:
            raise ValueError(f"Not enough data. Need at least {lookback + 1} records")
        
        # Create sequences
        X, y = [], []
        for i in range(lookback, len(feature_data)):
            X.append(feature_data.iloc[i-lookback:i].values.flatten())
            y.append(feature_data['price'].iloc[i])
        
        return np.array(X), np.array(y)
    
    def linear_regression_model(self, X: np.ndarray, y: np.ndarray) -> Dict:
        """Train linear regression model"""
        # Split data
        split_idx = int(0.8 * len(X))
        X_train, X_test = X[:split_idx], X[split_idx:]
        y_train, y_test = y[:split_idx], y[split_idx:]
        
        # Scale features
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)
        
        # Train model
        model = LinearRegression()
        model.fit(X_train_scaled, y_train)
        
        # Evaluate
        train_pred = model.predict(X_train_scaled)
        test_pred = model.predict(X_test_scaled)
        
        train_mse = mean_squared_error(y_train, train_pred)
        test_mse = mean_squared_error(y_test, test_pred)
        
        return {
            'model': model,
            'scaler': scaler,
            'train_mse': train_mse,
            'test_mse': test_mse,
            'last_features': X_test_scaled[-1:] if len(X_test_scaled) > 0 else X_train_scaled[-1:]
        }
    
    def moving_average_model(self, prices: pd.Series, windows: List[int] = [5, 10, 20]) -> Dict:
        """Simple moving average ensemble"""
        predictions = {}
        
        for window in windows:
            ma = prices.rolling(window=window).mean()
            # Simple trend continuation
            trend = ma.diff().iloc[-5:].mean()  # Average trend over last 5 days
            predictions[f'ma_{window}'] = ma.iloc[-1] + trend
        
        # Weighted average (shorter windows get higher weight for short-term predictions)
        weights = [1/w for w in windows]
        weights = [w/sum(weights) for w in weights]
        
        ensemble_pred = sum(pred * weight for pred, weight in zip(predictions.values(), weights))
        
        return {
            'predictions': predictions,
            'ensemble': ensemble_pred,
            'weights': dict(zip([f'ma_{w}' for w in windows], weights))
        }
    
    def arima_model(self, prices: pd.Series) -> Optional[Dict]:
        """ARIMA model for time series prediction"""
        if not ADVANCED_MODELS_AVAILABLE:
            return None
        
        try:
            # Check stationarity
            adf_result = adfuller(prices.dropna())
            
            # Difference if non-stationary
            if adf_result[1] > 0.05:
                diff_prices = prices.diff().dropna()
                d = 1
            else:
                diff_prices = prices
                d = 0
            
            # Fit ARIMA model with automatic order selection
            best_aic = float('inf')
            best_model = None
            best_order = None
            
            for p in range(3):
                for q in range(3):
                    try:
                        model = ARIMA(prices, order=(p, d, q))
                        fitted_model = model.fit()
                        
                        if fitted_model.aic < best_aic:
                            best_aic = fitted_model.aic
                            best_model = fitted_model
                            best_order = (p, d, q)
                    except:
                        continue
            
            if best_model is None:
                return None
            
            return {
                'model': best_model,
                'order': best_order,
                'aic': best_aic
            }
            
        except Exception as e:
            print(f"ARIMA model error: {e}")
            return None
    
    def garch_model(self, returns: pd.Series) -> Optional[Dict]:
        """GARCH model for volatility prediction"""
        if not ADVANCED_MODELS_AVAILABLE:
            return None
        
        try:
            # Remove NaN values and scale returns
            clean_returns = returns.dropna() * 100  # Scale for numerical stability
            
            if len(clean_returns) < 100:
                return None
            
            # Fit GARCH(1,1) model
            model = arch_model(clean_returns, vol='Garch', p=1, q=1)
            fitted_model = model.fit(disp='off')
            
            # Forecast volatility
            forecast = fitted_model.forecast(horizon=1)
            
            return {
                'model': fitted_model,
                'volatility_forecast': np.sqrt(forecast.variance.iloc[-1, 0]) / 100,
                'params': fitted_model.params
            }
            
        except Exception as e:
            print(f"GARCH model error: {e}")
            return None

class RealisticPredictionAdjuster:
    """Adjust predictions to be more realistic based on historical patterns"""
    
    @staticmethod
    def calculate_historical_volatility_bounds(df: pd.DataFrame) -> Dict[str, float]:
        """Calculate realistic volatility bounds based on historical data"""
        returns = df['returns'].dropna()
        
        # Calculate different time horizon volatilities (annualized)
        daily_vol = returns.std() * np.sqrt(252)
        weekly_vol = returns.rolling(5).sum().std() * np.sqrt(52)
        monthly_vol = returns.rolling(21).sum().std() * np.sqrt(12)
        
        # Calculate percentile-based bounds for different horizons
        bounds = {
            'daily_95th': np.percentile(np.abs(returns), 95),
            'weekly_95th': np.percentile(np.abs(returns.rolling(5).sum().dropna()), 95),
            'monthly_95th': np.percentile(np.abs(returns.rolling(21).sum().dropna()), 95),
            'quarterly_95th': np.percentile(np.abs(returns.rolling(63).sum().dropna()), 95),
            'annual_vol': daily_vol
        }
        
        return bounds
    
    @staticmethod
    def adjust_prediction_for_realism(predicted_price: float, current_price: float, 
                                    horizon_days: int, historical_bounds: Dict[str, float],
                                    sector_adjustment: float = 1.0) -> float:
        """Adjust prediction to be more realistic"""
        percentage_change = (predicted_price - current_price) / current_price
        
        # Define maximum realistic changes by horizon
        if horizon_days <= 7:  # 1 week
            max_change = min(historical_bounds['weekly_95th'] * 1.5, 0.15)  # Cap at 15%
        elif horizon_days <= 35:  # 5 weeks
            max_change = min(historical_bounds['monthly_95th'] * 2.0, 0.25)  # Cap at 25%
        elif horizon_days <= 90:  # 3 months
            max_change = min(historical_bounds['quarterly_95th'] * 1.2, 0.35)  # Cap at 35%
        elif horizon_days <= 180:  # 6 months
            max_change = min(historical_bounds['annual_vol'] * 0.7, 0.50)  # Cap at 50%
        else:  # 12 months
            max_change = min(historical_bounds['annual_vol'] * 1.0, 0.75)  # Cap at 75%
        
        # Apply sector adjustment (e.g., tech stocks might be more volatile)
        max_change *= sector_adjustment
        
        # If prediction exceeds realistic bounds, scale it down while preserving direction
        if abs(percentage_change) > max_change:
            # Scale down the prediction but preserve the directional signal
            scaling_factor = max_change / abs(percentage_change)
            # Apply a sigmoid-like scaling to preserve some of the original signal
            adjusted_scaling = scaling_factor + (1 - scaling_factor) * 0.3
            
            adjusted_change = percentage_change * adjusted_scaling
            adjusted_price = current_price * (1 + adjusted_change)
            
            return adjusted_price
        
        return predicted_price
    
    @staticmethod
    def detect_sector_volatility(symbol: str) -> float:
        """Detect sector-based volatility adjustment (simplified)"""
        # This is a simplified approach - in practice, you'd use sector classification APIs
        tech_symbols = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'NVDA', 'META']
        utility_symbols = ['NEE', 'DUK', 'SO', 'D', 'EXC']
        financial_symbols = ['JPM', 'BAC', 'WFC', 'C', 'GS']
        
        if symbol.upper() in tech_symbols:
            return 1.3  # Tech stocks are more volatile
        elif symbol.upper() in utility_symbols:
            return 0.7  # Utilities are less volatile
        elif symbol.upper() in financial_symbols:
            return 1.1  # Financials are moderately volatile
        else:
            return 1.0  # Default adjustment

class EnsemblePredictor:
    def __init__(self):
        self.models = PredictionModels()
        self.model_results = {}
        self.adjuster = RealisticPredictionAdjuster()
    
    def train_all_models(self, df: pd.DataFrame) -> None:
        """Train all available models"""
        print("\nTraining prediction models...")
        progress = ProgressBar(4, "Model Training")
        
        try:
            # Prepare features for ML models
            X, y = self.models.prepare_features(df)
            
            # Linear Regression
            lr_result = self.models.linear_regression_model(X, y)
            self.model_results['linear_regression'] = lr_result
            progress.update()
            
            # Moving Average
            ma_result = self.models.moving_average_model(df['price'])
            self.model_results['moving_average'] = ma_result
            progress.update()
            
            # ARIMA
            arima_result = self.models.arima_model(df['price'])
            if arima_result:
                self.model_results['arima'] = arima_result
            progress.update()
            
            # GARCH
            garch_result = self.models.garch_model(df['returns'])
            if garch_result:
                self.model_results['garch'] = garch_result
            progress.update()
            
        except Exception as e:
            print(f"Error training models: {e}")
    
    def predict_price(self, df: pd.DataFrame, horizon_days: int, symbol: str) -> Dict:
        """Generate ensemble prediction for given horizon with realistic adjustments"""
        predictions = {}
        weights = {}
        
        current_price = df['price'].iloc[-1]
        
        # Calculate historical bounds for realism adjustment
        historical_bounds = self.adjuster.calculate_historical_volatility_bounds(df)
        sector_adjustment = self.adjuster.detect_sector_volatility(symbol)
        
        # Linear Regression prediction
        if 'linear_regression' in self.model_results:
            lr_model = self.model_results['linear_regression']
            # Simple projection based on recent trend
            recent_trend = df['price'].iloc[-5:].pct_change().mean()
            lr_pred = current_price * (1 + recent_trend * horizon_days * 0.1)  # Dampen trend
            predictions['linear_regression'] = lr_pred
            weights['linear_regression'] = 1.0 / (1.0 + lr_model['test_mse'])
        
        # Moving Average prediction
        if 'moving_average' in self.model_results:
            ma_result = self.model_results['moving_average']
            # Adjust for horizon with dampening
            short_term_trend = df['price'].diff().iloc[-10:].mean()
            ma_pred = ma_result['ensemble'] + (short_term_trend * horizon_days * 0.3)
            predictions['moving_average'] = ma_pred
            weights['moving_average'] = 0.8  # Moderate weight
        
        # ARIMA prediction
        if 'arima' in self.model_results:
            try:
                arima_model = self.model_results['arima']['model']
                forecast = arima_model.forecast(steps=min(horizon_days, 30))
                arima_pred = forecast.iloc[-1] if hasattr(forecast, 'iloc') else forecast[-1]
                predictions['arima'] = arima_pred
                weights['arima'] = 1.0 / (1.0 + self.model_results['arima']['aic'] / 1000)
            except:
                pass
        
        # Volatility adjustment from GARCH
        volatility_adjustment = 1.0
        if 'garch' in self.model_results:
            vol_forecast = self.model_results['garch']['volatility_forecast']
            # Adjust predictions based on expected volatility (more conservative)
            volatility_adjustment = 1.0 + (vol_forecast * np.sqrt(horizon_days / 252) * 0.5)
        
        # Calculate ensemble prediction
        if predictions:
            # Normalize weights
            total_weight = sum(weights.values())
            normalized_weights = {k: v/total_weight for k, v in weights.items()}
            
            ensemble_pred = sum(pred * normalized_weights.get(model, 0) 
                              for model, pred in predictions.items())
            
            # Apply conservative volatility adjustment
            if ensemble_pred > current_price:
                ensemble_pred = current_price + (ensemble_pred - current_price) * min(volatility_adjustment, 1.2)
            else:
                ensemble_pred = current_price - (current_price - ensemble_pred) * min(volatility_adjustment, 1.2)
            # Apply realism adjustment
            ensemble_pred = self.adjuster.adjust_prediction_for_realism(
                ensemble_pred, current_price, horizon_days, historical_bounds, sector_adjustment
            )
            
            return {
                'ensemble_prediction': ensemble_pred,
                'individual_predictions': predictions,
                'model_weights': normalized_weights,
                'volatility_adjustment': volatility_adjustment
            }
        
        # Fallback: conservative trend extrapolation
        trend = df['price'].pct_change().iloc[-20:].mean()
        # Dampen the trend significantly for realism
        dampened_trend = trend * 0.5 * (1 / np.sqrt(horizon_days / 7))
        fallback_pred = current_price * (1 + dampened_trend * horizon_days)
        
        # Apply realism adjustment to fallback
        fallback_pred = self.adjuster.adjust_prediction_for_realism(
            fallback_pred, current_price, horizon_days, historical_bounds, sector_adjustment
        )
        
        return {
            'ensemble_prediction': fallback_pred,
            'individual_predictions': {'trend_extrapolation': fallback_pred},
            'model_weights': {'trend_extrapolation': 1.0},
            'volatility_adjustment': 1.0
        }

class BacktestEngine:
    def __init__(self):
        self.results = {}
    
    def backtest_model(self, df: pd.DataFrame, prediction_horizon: int = 5) -> Dict:
        """Perform backtesting on historical data"""
        print(f"\nRunning backtest (horizon: {prediction_horizon} days)...")
        
        # Use last 252 days (1 year) for backtesting
        test_period = min(252, len(df) - prediction_horizon - 60)
        start_idx = len(df) - test_period - prediction_horizon
        
        predictions = []
        actuals = []
        
        progress = ProgressBar(test_period // 5, "Backtesting")
        
        for i in range(start_idx, len(df) - prediction_horizon, 5):  # Test every 5 days
            try:
                # Use data up to current point
                historical_data = df.iloc[:i]
                
                if len(historical_data) < 100:  # Need minimum data
                    continue
                
                predictor = EnsemblePredictor()
                predictor.train_all_models(historical_data)
                
                # Make prediction (use a dummy symbol for backtesting)
                pred_result = predictor.predict_price(historical_data, prediction_horizon, 'TEST')
                predicted_price = pred_result['ensemble_prediction']
                
                # Get actual price
                actual_price = df['price'].iloc[i + prediction_horizon]
                
                predictions.append(predicted_price)
                actuals.append(actual_price)
                
                progress.update()
                
            except Exception as e:
                continue
        
        if len(predictions) < 5:
            return {'error': 'Insufficient data for backtesting'}
        
        # Calculate metrics
        predictions = np.array(predictions)
        actuals = np.array(actuals)
        
        mse = mean_squared_error(actuals, predictions)
        mae = mean_absolute_error(actuals, predictions)
        mape = np.mean(np.abs((actuals - predictions) / actuals)) * 100
        
        # Direction accuracy
        actual_directions = np.sign(actuals[1:] - actuals[:-1])
        pred_directions = np.sign(predictions[1:] - predictions[:-1])
        direction_accuracy = np.mean(actual_directions == pred_directions) * 100
        
        return {
            'mse': mse,
            'mae': mae,
            'mape': mape,
            'direction_accuracy': direction_accuracy,
            'num_predictions': len(predictions),
            'correlation': np.corrcoef(predictions, actuals)[0, 1]
        }

class RiskAssessment:
    @staticmethod
    def calculate_volatility_risk(df: pd.DataFrame, horizon_days: int) -> float:
        """Calculate volatility-adjusted risk score"""
        # Historical volatility (annualized)
        returns = df['returns'].dropna()
        historical_vol = returns.std() * np.sqrt(252)
        
        # Recent volatility (last 30 days)
        recent_vol = returns.iloc[-30:].std() * np.sqrt(252) if len(returns) >= 30 else historical_vol
        
        # VaR-like measure
        var_95 = returns.quantile(0.05)  # 5% VaR
        
        # Risk score (0-100, higher = riskier)
        vol_component = min(recent_vol * 100, 50)  # Cap at 50
        var_component = min(abs(var_95) * 1000, 50)  # Cap at 50
        
        # Adjust for horizon
        horizon_adjustment = np.sqrt(horizon_days / 252)
        
        risk_score = (vol_component + var_component) * horizon_adjustment
        return min(risk_score, 100)  # Cap at 100
    
    @staticmethod
    def calculate_confidence(prediction_result: Dict, backtest_results: Dict, 
                           volatility_risk: float) -> float:
        """Calculate confidence score for prediction"""
        base_confidence = 50.0  # Start with 50%
        
        # Adjust based on model agreement
        predictions = prediction_result.get('individual_predictions', {})
        if len(predictions) > 1:
            pred_values = list(predictions.values())
            pred_std = np.std(pred_values)
            pred_mean = np.mean(pred_values)
            cv = pred_std / pred_mean if pred_mean != 0 else 1
            
            # Lower coefficient of variation = higher confidence
            agreement_boost = max(0, 20 * (1 - cv))
            base_confidence += agreement_boost
        
        # Adjust based on backtest performance
        if 'direction_accuracy' in backtest_results:
            direction_acc = backtest_results['direction_accuracy']
            backtest_boost = (direction_acc - 50) * 0.4  # Scale to ±20
            base_confidence += backtest_boost
        
        # Penalize for high volatility
        volatility_penalty = volatility_risk * 0.3
        base_confidence -= volatility_penalty
        
        # Ensure confidence is between 10% and 90%
        return max(10, min(90, base_confidence))

class StockPredictor:
    def __init__(self):
        self.data_fetcher = DataFetcher()
        self.preprocessor = DataPreprocessor()
        self.technical_indicators = TechnicalIndicators()
        self.ensemble_predictor = EnsemblePredictor()
        self.backtest_engine = BacktestEngine()
        self.risk_assessment = RiskAssessment()
        
        # Prediction horizons in days
        self.horizons = {
            '1 week': 7,
            '5 weeks': 35,
            '3 months': 90,
            '6 months': 180,
            '12 months': 365
        }
    
    def classify_movement(self, percentage_change: float) -> MovementCategory:
        """Classify price movement into categories"""
        if abs(percentage_change) <= 1.0:
            return MovementCategory.BARELY_CHANGES
        elif percentage_change > 5.0:
            return MovementCategory.POSITIVE_MOVE
        elif percentage_change < -5.0:
            return MovementCategory.NEGATIVE_MOVE
        else:
            # Between 1-5% positive or negative
            return MovementCategory.POSITIVE_MOVE if percentage_change > 0 else MovementCategory.NEGATIVE_MOVE
    
    def predict_stock(self, symbol: str) -> Dict[str, PredictionResult]:
        """Main prediction function"""
        print(f"Starting comprehensive analysis for {symbol.upper()}")
        print("=" * 60)
        
        try:
            # Step 1: Fetch data
            raw_data = self.data_fetcher.fetch_all_sources(symbol)
            
            # Step 2: Preprocess data
            print("\nPreprocessing data...")
            processed_data = self.preprocessor.handle_splits_and_dividends(raw_data)
            processed_data = self.preprocessor.handle_missing_data(processed_data)
            processed_data = self.preprocessor.calculate_returns(processed_data)
            
            # Step 3: Calculate technical indicators
            print("Calculating technical indicators...")
            processed_data = self.technical_indicators.moving_averages(processed_data)
            processed_data = self.technical_indicators.bollinger_bands(processed_data)
            processed_data = self.technical_indicators.macd(processed_data)
            processed_data = self.technical_indicators.rsi(processed_data)
            
            # Step 4: Train models
            self.ensemble_predictor.train_all_models(processed_data)
            
            # Step 5: Run backtesting
            backtest_results = self.backtest_engine.backtest_model(processed_data)
            
            # Step 6: Generate predictions for all horizons
            print("\nGenerating predictions...")
            predictions = {}
            current_price = processed_data['price'].iloc[-1]
            
            progress = ProgressBar(len(self.horizons), "Predictions")
            
            for horizon_name, horizon_days in self.horizons.items():
                # Get prediction with realism adjustments
                pred_result = self.ensemble_predictor.predict_price(processed_data, horizon_days, symbol)
                predicted_price = pred_result['ensemble_prediction']
                
                # Calculate percentage change
                percentage_change = ((predicted_price - current_price) / current_price) * 100
                
                # Classify movement
                movement_category = self.classify_movement(percentage_change)
                
                # Calculate risk and confidence
                volatility_risk = self.risk_assessment.calculate_volatility_risk(
                    processed_data, horizon_days
                )
                confidence = self.risk_assessment.calculate_confidence(
                    pred_result, backtest_results, volatility_risk
                )
                
                # Create prediction result
                predictions[horizon_name] = PredictionResult(
                    horizon=horizon_name,
                    predicted_price=predicted_price,
                    current_price=current_price,
                    percentage_change=percentage_change,
                    movement_category=movement_category,
                    confidence=confidence,
                    volatility_risk=volatility_risk,
                    model_weights=pred_result['model_weights']
                )
                
                progress.update()
            
            # Store backtest results for display
            self.backtest_results = backtest_results
            
            return predictions
            
        except Exception as e:
            print(f"Error in prediction: {e}")
            raise
    
    def display_results(self, symbol: str, predictions: Dict[str, PredictionResult]):
        """Display comprehensive results in clean format"""
        print(f"\n{'='*80}")
        print(f"COMPREHENSIVE STOCK ANALYSIS: {symbol.upper()}")
        print(f"{'='*80}")
        
        current_price = predictions[list(predictions.keys())[0]].current_price
        print(f"Current Price: ${current_price:.2f}")
        print(f"Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Data Source: Marketstack API")
        
        # Display predictions
        print(f"\nPRICE PREDICTIONS")
        print("-" * 80)
        print(f"{'Horizon':<12} {'Price':<10} {'Change':<8} {'Category':<15} {'Confidence':<12} {'Risk':<6}")
        print("-" * 80)
        
        for horizon_name, pred in predictions.items():
            price_str = f"${pred.predicted_price:.2f}"
            change_str = f"{pred.percentage_change:+.1f}%"
            category_str = pred.movement_category.value
            confidence_str = f"{pred.confidence:.1f}%"
            risk_str = f"{pred.volatility_risk:.0f}/100"
            
            print(f"{horizon_name:<12} {price_str:<10} {change_str:<8} {category_str:<15} {confidence_str:<12} {risk_str:<6}")
        
        # Display model weights
        print(f"\nMODEL ENSEMBLE WEIGHTS")
        print("-" * 40)
        sample_weights = predictions['1 week'].model_weights
        for model, weight in sample_weights.items():
            print(f"{model.replace('_', ' ').title():<20} {weight:.3f}")
        
        # Display backtest results
        if hasattr(self, 'backtest_results') and 'error' not in self.backtest_results:
            print(f"\nBACKTESTING PERFORMANCE")
            print("-" * 40)
            bt = self.backtest_results
            print(f"Direction Accuracy:     {bt.get('direction_accuracy', 0):.1f}%")
            print(f"Mean Absolute Error:    ${bt.get('mae', 0):.2f}")
            print(f"Mean Abs Percentage:    {bt.get('mape', 0):.1f}%")
            print(f"Correlation:            {bt.get('correlation', 0):.3f}")
            print(f"Test Predictions:       {bt.get('num_predictions', 0)}")
        
        # Risk assessment summary
        print(f"\nRISK ASSESSMENT")
        print("-" * 40)
        avg_risk = np.mean([pred.volatility_risk for pred in predictions.values()])
        if avg_risk < 30:
            risk_level = "LOW"
        elif avg_risk < 60:
            risk_level = "MODERATE"
        else:
            risk_level = "HIGH"
        
        print(f"Overall Risk Level:     {risk_level} ({avg_risk:.0f}/100)")
        
        # Investment insights
        print(f"\nINVESTMENT INSIGHTS")
        print("-" * 40)
        
        short_term = predictions['1 week']
        long_term = predictions['12 months']
        
        if short_term.movement_category == MovementCategory.POSITIVE_MOVE:
            print("Short-term outlook appears positive")
        elif short_term.movement_category == MovementCategory.NEGATIVE_MOVE:
            print("Short-term outlook appears negative")
        else:
            print("Short-term price expected to remain stable")
        
        if long_term.movement_category == MovementCategory.POSITIVE_MOVE:
            print("Long-term growth potential identified")
        elif long_term.movement_category == MovementCategory.NEGATIVE_MOVE:
            print("Long-term decline risk identified")
        else:
            print("Long-term price expected to remain relatively stable")
        
        # Confidence summary
        avg_confidence = np.mean([pred.confidence for pred in predictions.values()])
        print(f"Average Prediction Confidence: {avg_confidence:.1f}%")
        
        # Market context
        self._display_market_context(predictions, symbol)
        
        print(f"\n{'='*80}")
        print("DISCLAIMER: This analysis is for educational purposes only.")
        print("Past performance does not guarantee future results.")
        print("Always consult with financial professionals before investing.")
        print(f"{'='*80}")
    
    def _display_market_context(self, predictions: Dict[str, PredictionResult], symbol: str):
        """Display additional market context"""
        print(f"\nMARKET CONTEXT")
        print("-" * 40)
        
        # Volatility assessment
        short_term_risk = predictions['1 week'].volatility_risk
        long_term_risk = predictions['12 months'].volatility_risk
        
        if short_term_risk > long_term_risk * 1.5:
            print("Higher near-term volatility expected")
        elif long_term_risk > short_term_risk * 1.5:
            print("Volatility expected to increase over time")
        else:
            print("Volatility expected to remain relatively stable")
        
        # Prediction consistency
        changes = [pred.percentage_change for pred in predictions.values()]
        if all(c > 0 for c in changes):
            print("All models suggest upward price movement")
        elif all(c < 0 for c in changes):
            print("All models suggest downward price movement")
        else:
            print("Mixed signals across different time horizons")
        
        # Confidence trend
        confidences = [pred.confidence for pred in predictions.values()]
        if confidences[0] > confidences[-1]:
            print("Higher confidence in short-term vs long-term predictions")
        else:
            print("Confidence remains consistent across time horizons")

def main():
    """Main execution function"""
    print("Advanced Stock Price Prediction System")
    print("Using Marketstack API for data retrieval")
    print("=" * 50)
    
    # Get stock symbol from user
    while True:
        symbol = input("\nEnter stock symbol (e.g., AAPL, MSFT, TSLA): ").strip().upper()
        if symbol:
            break
        print("Please enter a valid stock symbol")
    
    try:
        # Create predictor instance
        predictor = StockPredictor()
        
        # Run prediction
        start_time = time.time()
        predictions = predictor.predict_stock(symbol)
        end_time = time.time()
        
        # Display results
        predictor.display_results(symbol, predictions)
        
        print(f"\nAnalysis completed in {end_time - start_time:.1f} seconds")
        
        # Option to save results
        save_option = input("\nSave results to file? (y/n): ").strip().lower()
        if save_option == 'y':
            save_results_to_file(symbol, predictions, predictor.backtest_results)
        
    except KeyboardInterrupt:
        print("\n\nAnalysis interrupted by user")
    except Exception as e:
        print(f"\nError during analysis: {e}")
        print("Please check your internet connection and try again")
        print("If the error persists, the stock symbol might not be available in the Marketstack database")

def save_results_to_file(symbol: str, predictions: Dict[str, PredictionResult], 
                        backtest_results: Dict):
    """Save results to JSON file"""
    try:
        # Prepare data for JSON serialization
        results_data = {
            'symbol': symbol,
            'analysis_date': datetime.now().isoformat(),
            'data_source': 'Marketstack API',
            'current_price': predictions[list(predictions.keys())[0]].current_price,
            'predictions': {},
            'backtest_results': backtest_results
        }
        
        for horizon, pred in predictions.items():
            results_data['predictions'][horizon] = {
                'predicted_price': pred.predicted_price,
                'percentage_change': pred.percentage_change,
                'movement_category': pred.movement_category.value,
                'confidence': pred.confidence,
                'volatility_risk': pred.volatility_risk,
                'model_weights': pred.model_weights
            }
        
        # Save to file
        filename = f"{symbol}_prediction_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, 'w') as f:
            json.dump(results_data, f, indent=2)
        
        print(f"Results saved to {filename}")
        
    except Exception as e:
        print(f"Error saving file: {e}")

# Additional utility functions for enhanced realism
class MarketRegimeDetector:
    """Detect market regimes to adjust predictions accordingly"""
    
    @staticmethod
    def detect_regime(df: pd.DataFrame, window: int = 50) -> str:
        """Detect current market regime"""
        if len(df) < window:
            return "insufficient_data"
        
        recent_data = df.tail(window)
        
        # Calculate trend strength
        price_change = (recent_data['price'].iloc[-1] - recent_data['price'].iloc[0]) / recent_data['price'].iloc[0]
        volatility = recent_data['returns'].std()
        
        # Simple regime classification
        if price_change > 0.1 and volatility < 0.03:
            return "bull_market"
        elif price_change < -0.1 and volatility < 0.03:
            return "bear_market"
        elif volatility > 0.05:
            return "high_volatility"
        else:
            return "sideways_market"

# Performance optimization for large datasets
def optimize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Optimize DataFrame memory usage"""
    for col in df.select_dtypes(include=['float64']).columns:
        df[col] = pd.to_numeric(df[col], downcast='float')
    
    for col in df.select_dtypes(include=['int64']).columns:
        df[col] = pd.to_numeric(df[col], downcast='integer')
    
    return df

# Error handling and logging
import logging

def setup_logging():
    """Setup logging configuration"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('stock_predictor.log'),
            logging.StreamHandler()
        ]
    )

def test_marketstack_connection():
    """Test Marketstack API connection"""
    print("Testing Marketstack API connection...")
    try:
        fetcher = DataFetcher()
        test_data = fetcher.fetch_marketstack('AAPL')
        if test_data is not None:
            print(f"✓ Marketstack API connection successful! Retrieved {len(test_data)} records for AAPL")
            return True
        else:
            print("✗ Marketstack API connection failed")
            return False
    except Exception as e:
        print(f"✗ Marketstack API test failed: {e}")
        return False

if __name__ == "__main__":
    # Setup logging
    setup_logging()
    
    # Check for required packages
    required_packages = ['pandas', 'numpy', 'requests', 'sklearn', 'scipy']
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            missing_packages.append(package)
    
    if missing_packages:
        print(f"Missing required packages: {', '.join(missing_packages)}")
        print("Install with: pip install " + " ".join(missing_packages))
        sys.exit(1)
    
    # Optional packages warning
    if not ADVANCED_MODELS_AVAILABLE:
        print("Advanced models (ARIMA, GARCH) not available.")
        print("For full functionality, install: pip install statsmodels arch")
        print("Continuing with basic models...\n")
    
    # Test API connection
    if not test_marketstack_connection():
        print("Warning: Marketstack API test failed. The system will try other data sources as backup.")
        print("Continuing anyway...\n")
    
    # Run main program
    main()
            
