import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import json
import joblib
import os
import math
import unicodedata
import warnings
from urllib.parse import urlparse
from collections import Counter

from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import (
    accuracy_score, f1_score, precision_score,
    recall_score, confusion_matrix
)
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, AdaBoostClassifier, BaggingClassifier
from sklearn.tree import DecisionTreeClassifier
from sklearn.neighbors import KNeighborsClassifier
from sklearn.naive_bayes import GaussianNB
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.svm import SVC
from sklearn.neural_network import MLPClassifier
from sklearn.utils import resample
from sklearn.preprocessing import StandardScaler
from sklearn.base import BaseEstimator, ClassifierMixin
from xgboost import XGBClassifier
from lightgbm import LGBMClassifier
from catboost import CatBoostClassifier

try:
    import onnxmltools
    from onnxmltools.convert.common.data_types import FloatTensorType as ONNXFloatTensorType
    ONNXMLTOOLS_AVAILABLE = True
except ImportError:
    ONNXMLTOOLS_AVAILABLE = False
    print("Warning: onnxmltools not installed. XGBoost/CatBoost ONNX export will be skipped.")

from skl2onnx import convert_sklearn
from skl2onnx.common.data_types import FloatTensorType
import onnxruntime as rt

warnings.filterwarnings('ignore')

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
DATA_PATH = os.environ.get(
    'HOMOGRAPH_DATA_PATH',
    os.path.join(os.path.dirname(__file__), 'homograph-url.csv')
)
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

FEATURES = [
    'url_length', 'domain_length', 'char_entropy', 'digit_fraction',
    'special_char_fraction', 'unicode_fraction', 'subdomain_depth',
    'has_punycode', 'unicode_script_count', 'mixed_script',
    'vowel_consonant_ratio', 'max_consec_consonants'
]

SVM_SAMPLE_SIZE = 10_000
RANDOM_STATE = 42

VOWELS = set('aeiouAEIOU')
CONSONANTS = set('bcdfghjklmnpqrstvwxyzBCDFGHJKLMNPQRSTVWXYZ')

# ---------------------------------------------------------------------------
# Feature extraction helpers
# ---------------------------------------------------------------------------

def get_domain(url: str) -> str:
    url = str(url)
    if not url.startswith('http'):
        url = 'http://' + url
    try:
        return urlparse(url).netloc
    except Exception:
        return url


def char_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = Counter(s)
    total = len(s)
    return -sum((c / total) * math.log2(c / total) for c in counts.values())


def get_unicode_script(ch: str) -> str:
    try:
        name = unicodedata.name(ch, '')
        if name:
            return name.split()[0]
    except Exception:
        pass
    return 'UNKNOWN'


def extract_features(url: str) -> dict:
    url = str(url)
    if not url.startswith('http'):
        url_full = 'http://' + url
    else:
        url_full = url

    try:
        parsed = urlparse(url_full)
        domain = parsed.netloc or url
        path   = parsed.path or ''
    except Exception:
        domain = url
        path   = ''

    full = domain + path

    # Basic length features
    url_length    = len(url)
    domain_length = len(domain)

    # Character fractions over full URL string
    total = max(len(full), 1)
    digit_frac   = sum(c.isdigit()    for c in full) / total
    special_frac = sum(not c.isalnum() for c in full) / total
    unicode_frac = sum(ord(c) > 127    for c in full) / total

    # Entropy of domain only
    entropy = char_entropy(domain)

    # Subdomain depth (number of dots in netloc minus 1, min 0)
    parts = domain.split('.')
    subdomain_depth = max(len(parts) - 2, 0)

    # Punycode
    has_punycode = int('xn--' in domain.lower())

    # Unicode script variety (over domain)
    scripts = set()
    for ch in domain:
        if ord(ch) > 127:
            scripts.add(get_unicode_script(ch))
    unicode_script_count = len(scripts)
    mixed_script = int(unicode_script_count > 1)

    # Vowel / consonant ratio (over domain letters)
    letters = [c for c in domain if c.isalpha()]
    vowels    = sum(c in VOWELS    for c in letters)
    consonants= sum(c in CONSONANTS for c in letters)
    vowel_consonant_ratio = vowels / max(consonants, 1)

    # Max consecutive consonants
    max_cc = 0
    cur_cc = 0
    for c in domain:
        if c in CONSONANTS:
            cur_cc += 1
            max_cc = max(max_cc, cur_cc)
        else:
            cur_cc = 0

    return {
        'url_length':            url_length,
        'domain_length':         domain_length,
        'char_entropy':          entropy,
        'digit_fraction':        digit_frac,
        'special_char_fraction': special_frac,
        'unicode_fraction':      unicode_frac,
        'subdomain_depth':       subdomain_depth,
        'has_punycode':          has_punycode,
        'unicode_script_count':  unicode_script_count,
        'mixed_script':          mixed_script,
        'vowel_consonant_ratio': vowel_consonant_ratio,
        'max_consec_consonants': max_cc,
    }


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def load_and_preprocess(path: str) -> pd.DataFrame:
    print(f"Loading dataset from: {path}")
    df = pd.read_csv(path)
    print(f"Raw rows: {len(df):,}  |  Columns: {list(df.columns)}")

    # Support both CSV schemas:
    #   OLD: pre-computed feature columns + 'label' + 'url'
    #   NEW: 'url' + 'classification'
    if 'label' not in df.columns and 'classification' in df.columns:
        label_map = {'legitimate': 0, 'unsafe': 1, 'phishing': 1}
        df['label'] = df['classification'].str.strip().str.lower().map(label_map)
        df = df.dropna(subset=['label', 'url'])
        df['label'] = df['label'].astype(int)

        print("Extracting features from URLs (this may take a minute)...")
        feat_rows = df['url'].apply(extract_features)
        feat_df   = pd.DataFrame(list(feat_rows))
        df = pd.concat([df.reset_index(drop=True), feat_df], axis=1)
    else:
        # Old schema — boolean columns to int
        df['has_punycode'] = df['has_punycode'].astype(int)
        df['mixed_script']  = df['mixed_script'].astype(int)
        df = df.dropna(subset=FEATURES + ['label', 'url'])

    df['parsed_domain'] = df['url'].apply(get_domain)

    print(f"Dataset size after cleaning: {len(df):,} rows")
    print(f"Class distribution:\n{df['label'].value_counts(normalize=True).round(3)}")
    return df


def split_data(df: pd.DataFrame):
    X = df[FEATURES]
    y = df['label']
    groups = df['parsed_domain']

    gss = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=RANDOM_STATE)
    train_idx, test_idx = next(gss.split(X, y, groups))

    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
    y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

    print(f"Train size: {len(X_train):,} | Test size: {len(X_test):,}")
    return X_train, X_test, y_train, y_test


def scale_data(X_train, X_test):
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled  = scaler.transform(X_test)

    joblib.dump(scaler, os.path.join(OUTPUT_DIR, 'scaler.pkl'))
    np.save(os.path.join(OUTPUT_DIR, 'scaler_mean.npy'),  scaler.mean_)
    np.save(os.path.join(OUTPUT_DIR, 'scaler_scale.npy'), scaler.scale_)

    return X_train_scaled, X_test_scaled, scaler


# ---------------------------------------------------------------------------
# LCCDE - Leader Class and Confidence Decision Ensemble
# ---------------------------------------------------------------------------

class LCCDE(BaseEstimator, ClassifierMixin):
    """
    Leader Class and Confidence Decision Ensemble (LCCDE)
    An ensemble method that combines predictions from multiple classifiers
    based on class confidence and leader class mechanism.
    """
    def __init__(self, n_estimators=5, random_state=42):
        self.n_estimators = n_estimators
        self.random_state = random_state
        self.estimators_ = []
        self.weights_ = None
        
    def fit(self, X, y):
        """Fit the LCCDE ensemble"""
        np.random.seed(self.random_state)
        
        # Base learners for the ensemble
        base_estimators = [
            DecisionTreeClassifier(max_depth=7, random_state=self.random_state),
            LogisticRegression(max_iter=500, random_state=self.random_state),
            KNeighborsClassifier(n_neighbors=5),
            GaussianNB(),
            DecisionTreeClassifier(max_depth=5, random_state=self.random_state + 1)
        ]
        
        self.estimators_ = base_estimators[:self.n_estimators]
        
        # Fit all base estimators
        for est in self.estimators_:
            est.fit(X, y)
        
        # Compute confidence weights based on training accuracy
        confidences = []
        for est in self.estimators_:
            y_pred = est.predict(X)
            acc = accuracy_score(y, y_pred)
            confidences.append(max(acc, 0.01))  # Avoid zero weights
        
        self.weights_ = np.array(confidences) / np.sum(confidences)
        return self
    
    def predict(self, X):
        """Make predictions using weighted voting"""
        predictions = np.array([est.predict(X) for est in self.estimators_])
        
        # Weighted voting
        weighted_votes = np.zeros((X.shape[0], 2))
        for i, pred in enumerate(predictions):
            for j, p in enumerate(pred):
                weighted_votes[j, p] += self.weights_[i]
        
        return np.argmax(weighted_votes, axis=1)
    
    def predict_proba(self, X):
        """Predict class probabilities"""
        predictions = np.array([est.predict_proba(X) for est in self.estimators_])
        
        # Weighted average of probabilities
        proba = np.zeros_like(predictions[0])
        for i, pred in enumerate(predictions):
            proba += self.weights_[i] * pred
        
        return proba / np.sum(self.weights_)


def build_models() -> dict:
    # --- Check for GPU support dynamically ---
    print("\nChecking for GPU acceleration support...")
    xgb_gpu = {}
    try:
        XGBClassifier(n_estimators=1, tree_method='hist', device='cuda').fit(np.array([[0.1, 0.2], [0.3, 0.4]]), np.array([0, 1]))
        xgb_gpu = {'tree_method': 'hist', 'device': 'cuda'}
        print(" -> XGBoost: GPU enabled")
    except Exception:
        try:
            XGBClassifier(n_estimators=1, tree_method='gpu_hist').fit(np.array([[0.1, 0.2], [0.3, 0.4]]), np.array([0, 1]))
            xgb_gpu = {'tree_method': 'gpu_hist'}
            print(" -> XGBoost: GPU enabled (legacy)")
        except Exception:
            print(" -> XGBoost: GPU not available, using CPU")

    cat_gpu = {}
    try:
        CatBoostClassifier(iterations=1, task_type='GPU', verbose=0).fit(np.array([[0.1, 0.2], [0.3, 0.4]]), np.array([0, 1]))
        cat_gpu = {'task_type': 'GPU'}
        print(" -> CatBoost: GPU enabled")
    except Exception:
        print(" -> CatBoost: GPU not available, using CPU")

    lgb_gpu = {}
    try:
        LGBMClassifier(n_estimators=1, device='gpu', verbose=-1).fit(np.array([[0.1, 0.2], [0.3, 0.4]]), np.array([0, 1]))
        lgb_gpu = {'device': 'gpu'}
        print(" -> LightGBM: GPU enabled")
    except Exception:
        print(" -> LightGBM: GPU not available, using CPU")
    # ----------------------------------------

    return {
        'Logistic Regression': LogisticRegression(
            random_state=RANDOM_STATE, max_iter=1000
        ),
        'Decision Tree': DecisionTreeClassifier(
            random_state=RANDOM_STATE
        ),
        'KNN': KNeighborsClassifier(n_jobs=-1),
        'Naive Bayes': GaussianNB(),
        'LDA': LinearDiscriminantAnalysis(),
        'AdaBoost': AdaBoostClassifier(
            random_state=RANDOM_STATE
        ),
        'Bagging': BaggingClassifier(
            random_state=RANDOM_STATE, n_jobs=-1
        ),
        'Random Forest': RandomForestClassifier(
            n_estimators=100, random_state=RANDOM_STATE, n_jobs=-1
        ),
        'XGBoost': XGBClassifier(
            eval_metric='logloss', random_state=RANDOM_STATE, n_jobs=-1, **xgb_gpu
        ),
        'LightGBM': LGBMClassifier(
            n_estimators=300, learning_rate=0.05,
            num_leaves=63, random_state=RANDOM_STATE, n_jobs=-1, verbose=-1, **lgb_gpu
        ),
        'CatBoost': CatBoostClassifier(
            iterations=300, learning_rate=0.05, depth=6,
            random_seed=RANDOM_STATE, thread_count=-1, verbose=0, **cat_gpu
        ),
        'SVM': SVC(
            kernel='rbf', probability=True, random_state=RANDOM_STATE
        ),
        'Neural Network (MLP)': MLPClassifier(
            hidden_layer_sizes=(64, 32), max_iter=300,
            early_stopping=True, random_state=RANDOM_STATE
        ),
        'LCCDE': LCCDE(
            n_estimators=5, random_state=RANDOM_STATE
        ),
    }


def train_and_evaluate(models, X_train_scaled, X_test_scaled, y_train, y_test):
    results = {}
    best_model_name = ""
    best_f1 = 0.0
    best_model = None

    for name, model in models.items():
        print(f"\nTraining {name}...")

        if name == 'SVM':
            X_svm, y_svm = resample(
                X_train_scaled, y_train,
                n_samples=SVM_SAMPLE_SIZE,
                random_state=RANDOM_STATE,
                stratify=y_train
            )
            model.fit(X_svm, y_svm)
        elif name == 'CatBoost':
            # CatBoost accepts numpy arrays directly; pass unscaled works fine
            # but we keep scaled for consistency across all models
            model.fit(X_train_scaled, y_train)
        else:
            model.fit(X_train_scaled, y_train)

        y_pred = model.predict(X_test_scaled)

        acc  = accuracy_score(y_test, y_pred)
        f1   = f1_score(y_test, y_pred)
        prec = precision_score(y_test, y_pred)
        rec  = recall_score(y_test, y_pred)

        results[name] = {
            'Accuracy': acc, 'F1': f1,
            'Precision': prec, 'Recall': rec
        }
        print(
            f"  Acc: {acc:.4f} | F1: {f1:.4f} | "
            f"Prec: {prec:.4f} | Rec: {rec:.4f}"
        )

        if f1 > best_f1:
            best_f1         = f1
            best_model_name = name
            best_model      = model

    print(f"\nBest model: {best_model_name}  (F1 = {best_f1:.4f})")
    return results, best_model_name, best_model


def plot_results(best_model, best_model_name, X_test_scaled, y_test):
    print(f"\nGenerating plots for {best_model_name}...")
    y_pred = best_model.predict(X_test_scaled)

    cm = confusion_matrix(y_test, y_pred)
    plt.figure(figsize=(6, 5))
    sns.heatmap(
        cm, annot=True, fmt='d', cmap='Blues',
        xticklabels=['Legitimate', 'Unsafe'],
        yticklabels=['Legitimate', 'Unsafe']
    )
    plt.ylabel('Actual')
    plt.xlabel('Predicted')
    plt.title(f'Confusion Matrix — {best_model_name}')
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'confusion_matrix.png'), dpi=150)
    plt.close()

    if hasattr(best_model, 'feature_importances_'):
        importances = best_model.feature_importances_
        indices = np.argsort(importances)[::-1]
        plt.figure(figsize=(10, 6))
        plt.title(f'Feature Importances — {best_model_name}')
        plt.bar(range(len(FEATURES)), importances[indices], align='center')
        plt.xticks(
            range(len(FEATURES)),
            np.array(FEATURES)[indices],
            rotation=45, ha='right'
        )
        plt.tight_layout()
        plt.savefig(os.path.join(OUTPUT_DIR, 'feature_importance.png'), dpi=150)
        plt.close()
        print("Saved: confusion_matrix.png, feature_importance.png")
    else:
        print("Saved: confusion_matrix.png (no feature importance for this model type)")


def export_onnx(best_model, best_model_name: str):
    print(f"\nExporting {best_model_name} to ONNX...")
    onnx_path = os.path.join(OUTPUT_DIR, 'model.onnx')

    if best_model_name == 'XGBoost':
        if not ONNXMLTOOLS_AVAILABLE:
            print("Skipping ONNX export: onnxmltools not installed.")
            return
        initial_type = [('float_input', ONNXFloatTensorType([None, len(FEATURES)]))]
        onnx_model = onnxmltools.convert_xgboost(best_model, initial_types=initial_type)
    elif best_model_name == 'CatBoost':
        if not ONNXMLTOOLS_AVAILABLE:
            print("Skipping ONNX export: onnxmltools not installed.")
            return
        initial_type = [('float_input', ONNXFloatTensorType([None, len(FEATURES)]))]
        onnx_model = onnxmltools.convert_catboost(best_model, initial_types=initial_type)
    elif best_model_name == 'LightGBM':
        try:
            from onnxmltools.convert import convert_lightgbm as _convert_lgbm
            initial_type = [('float_input', ONNXFloatTensorType([None, len(FEATURES)]))]
            onnx_model = _convert_lgbm(best_model, initial_types=initial_type)
        except Exception:
            # Fallback: treat as sklearn-compatible via skl2onnx
            initial_type = [('float_input', FloatTensorType([None, len(FEATURES)]))]
            onnx_model = convert_sklearn(best_model, initial_types=initial_type)
    else:
        initial_type = [('float_input', FloatTensorType([None, len(FEATURES)]))]
        onnx_model = convert_sklearn(best_model, initial_types=initial_type)

    with open(onnx_path, 'wb') as f:
        f.write(onnx_model.SerializeToString())

    print("Verifying ONNX export...")
    sess = rt.InferenceSession(onnx_path)
    dummy_input = np.zeros((1, len(FEATURES)), dtype=np.float32)
    input_name  = sess.get_inputs()[0].name
    sess.run(None, {input_name: dummy_input})
    print(f"ONNX export verified: {onnx_path}")


def save_metadata(results: dict):
    features_path = os.path.join(OUTPUT_DIR, 'features.json')
    with open(features_path, 'w') as f:
        json.dump(FEATURES, f, indent=2)
    print(f"Saved feature list: {features_path}")

    results_path = os.path.join(OUTPUT_DIR, 'model_results.json')
    with open(results_path, 'w') as f:
        json.dump(
            {k: {m: round(v, 4) for m, v in metrics.items()}
             for k, metrics in results.items()},
            f, indent=2
        )
    print(f"Saved results: {results_path}")


def print_summary(results: dict, best_model_name: str):
    print("\n" + "=" * 58)
    print(f"{'Model':<28} {'Acc':>6} {'F1':>6} {'Prec':>7} {'Rec':>7}")
    print("-" * 58)
    for name, m in results.items():
        marker = " <-- best" if name == best_model_name else ""
        print(
            f"{name:<28} {m['Accuracy']:>6.4f} {m['F1']:>6.4f} "
            f"{m['Precision']:>7.4f} {m['Recall']:>7.4f}{marker}"
        )
    print("=" * 58)


def main():
    # 1. Load & preprocess (auto-detects CSV schema)
    df = load_and_preprocess(DATA_PATH)

    # 2. Split (group-aware — no domain leakage)
    X_train, X_test, y_train, y_test = split_data(df)

    # 3. Scale (fit on train only)
    X_train_scaled, X_test_scaled, scaler = scale_data(X_train, X_test)

    # 4. Train all models
    models = build_models()
    results, best_model_name, best_model = train_and_evaluate(
        models, X_train_scaled, X_test_scaled, y_train, y_test
    )

    # 5. Results table
    print_summary(results, best_model_name)

    # 6. Plots
    plot_results(best_model, best_model_name, X_test_scaled, y_test)

    # 7. Export to ONNX + verify
    export_onnx(best_model, best_model_name)

    # 8. Save features.json + results JSON
    save_metadata(results)

    print("\nDone. Output files:")
    for fname in ['model.onnx', 'scaler.pkl', 'scaler_mean.npy',
                  'scaler_scale.npy', 'features.json', 'model_results.json',
                  'confusion_matrix.png', 'feature_importance.png']:
        fpath = os.path.join(OUTPUT_DIR, fname)
        exists = "OK" if os.path.exists(fpath) else "not created"
        print(f"  {fname:<30} {exists}")

if __name__ == '__main__':
    main()