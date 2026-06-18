export type ConfigField =
  | { id: string; label: string; type: 'text'; default: string }
  | { id: string; label: string; type: 'number'; default: number; min?: number; max?: number; step?: number }
  | { id: string; label: string; type: 'select'; default: string; options: string[] }
  | { id: string; label: string; type: 'toggle'; default: boolean }
  | { id: string; label: string; type: 'textarea'; default: string; mono?: boolean }
  | { id: string; label: string; type: 'file'; default: string; accept?: string }
  | { id: string; label: string; type: 'hp_params'; default: Array<{ key: string; values: string }> }
  | { id: string; label: string; type: 'col_map'; default: Array<{ key: string; values: string }> }

export type PortType =
  | 'dataset' | 'train' | 'test' | 'val' | 'folds'
  | 'X_train' | 'y_train' | 'X_val' | 'y_val' | 'X_test' | 'y_test'
  | 'model' | 'predictions' | 'report' | 'plot' | 'endpoint'
  | 'outliers' | 'pipeline' | 'hpconfig' | 'transformer'

export type NodeCategory =
  | 'data' | 'quality' | 'feature' | 'balance' | 'split'
  | 'model' | 'advanced' | 'ensemble' | 'eval' | 'interp' | 'deploy' | 'monitor'

export interface PortSpec { name: string; type: PortType }

export interface NodeSpec {
  type: string
  label: string
  category: NodeCategory
  description: string
  inputs: PortSpec[]
  outputs: PortSpec[]
  config: ConfigField[]
}

export interface CategoryMeta {
  label: string
  color: string
  icon: string
}

export const CATEGORY_META: Record<NodeCategory, CategoryMeta> = {
  data:     { label: 'Data Input',       color: 'var(--cat-data)',     icon: '⊞' },
  quality:  { label: 'Data Quality',     color: 'var(--cat-quality)',  icon: '✦' },
  feature:  { label: 'Feature Eng.',     color: 'var(--cat-feature)',  icon: '◈' },
  balance:  { label: 'Data Balancing',   color: 'var(--cat-balance)',  icon: '⊜' },
  split:    { label: 'Data Split',       color: 'var(--cat-split)',    icon: '⋈' },
  model:    { label: 'Models',           color: 'var(--cat-model)',    icon: '◉' },
  advanced: { label: 'Advanced ML',      color: 'var(--cat-advanced)', icon: '◎' },
  ensemble: { label: 'Ensemble',         color: 'var(--cat-ensemble)', icon: '⊕' },
  eval:     { label: 'Evaluation',       color: 'var(--cat-eval)',     icon: '◇' },
  interp:   { label: 'Interpretability', color: 'var(--cat-interp)',   icon: '◑' },
  deploy:   { label: 'Deployment',       color: 'var(--cat-deploy)',   icon: '⊳' },
  monitor:  { label: 'Monitoring',       color: 'var(--cat-monitor)',  icon: '◐' },
}

export const NODE_REGISTRY: Record<string, NodeSpec> = {
  // ── DATA INPUT ────────────────────────────────────────────────────────────
  csv_loader: {
    type: 'csv_loader', label: 'CSV Loader', category: 'data',
    description: 'Load data from a CSV file',
    inputs: [], outputs: [{ name: 'dataset', type: 'dataset' }],
    config: [
      { id: 'path', label: 'File Path', type: 'file', default: '', accept: '.csv,.tsv,.txt,text/csv' },
      { id: 'sep', label: 'Separator', type: 'select', options: [',', ';', '\\t', '|'], default: ',' },
      { id: 'header', label: 'Header Row', type: 'toggle', default: true },
      { id: 'encoding', label: 'Encoding', type: 'select', options: ['utf-8', 'latin-1', 'utf-16'], default: 'utf-8' },
    ],
  },
  excel_loader: {
    type: 'excel_loader', label: 'Excel Loader', category: 'data',
    description: 'Load data from an Excel file',
    inputs: [], outputs: [{ name: 'dataset', type: 'dataset' }],
    config: [
      { id: 'path', label: 'File Path', type: 'file', default: '', accept: '.xlsx,.xls,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' },
      { id: 'sheet', label: 'Sheet Name', type: 'text', default: 'Sheet1' },
      { id: 'header', label: 'Header Row', type: 'toggle', default: true },
    ],
  },
  json_loader: {
    type: 'json_loader', label: 'JSON Loader', category: 'data',
    description: 'Load structured JSON data',
    inputs: [], outputs: [{ name: 'dataset', type: 'dataset' }],
    config: [
      { id: 'path', label: 'File Path', type: 'text', default: 'data.json' },
      { id: 'orient', label: 'Orientation', type: 'select', options: ['records', 'index', 'columns', 'values'], default: 'records' },
    ],
  },
  db_connector: {
    type: 'db_connector', label: 'DB Connector', category: 'data',
    description: 'Connect to MySQL / PostgreSQL',
    inputs: [], outputs: [{ name: 'dataset', type: 'dataset' }],
    config: [
      { id: 'host', label: 'Host', type: 'text', default: 'localhost' },
      { id: 'port', label: 'Port', type: 'number', default: 5432 },
      { id: 'db', label: 'Database', type: 'text', default: 'mydb' },
      { id: 'query', label: 'SQL Query', type: 'textarea', default: 'SELECT * FROM table LIMIT 1000' },
    ],
  },
  api_fetch: {
    type: 'api_fetch', label: 'API Fetch', category: 'data',
    description: 'Fetch data from a REST API endpoint',
    inputs: [], outputs: [{ name: 'dataset', type: 'dataset' }],
    config: [
      { id: 'url', label: 'URL', type: 'text', default: 'https://api.example.com/data' },
      { id: 'method', label: 'Method', type: 'select', options: ['GET', 'POST'], default: 'GET' },
      { id: 'auth', label: 'Auth Token', type: 'text', default: '' },
    ],
  },
  synth_data: {
    type: 'synth_data', label: 'Synthetic Data', category: 'data',
    description: 'Generate synthetic training data',
    inputs: [], outputs: [{ name: 'dataset', type: 'dataset' }],
    config: [
      { id: 'rows', label: 'Rows', type: 'number', default: 1000 },
      { id: 'features', label: 'Features', type: 'number', default: 10 },
      { id: 'task', label: 'Task Type', type: 'select', options: ['classification', 'regression', 'clustering'], default: 'classification' },
    ],
  },
  data_merge: {
    type: 'data_merge', label: 'Data Merge / Join', category: 'data',
    description: 'Merge two datasets on a key column',
    inputs: [{ name: 'left', type: 'dataset' }, { name: 'right', type: 'dataset' }],
    outputs: [{ name: 'dataset', type: 'dataset' }],
    config: [
      { id: 'on', label: 'Join Key', type: 'text', default: 'id' },
      { id: 'how', label: 'Join Type', type: 'select', options: ['inner', 'left', 'right', 'outer'], default: 'inner' },
    ],
  },
  manual_input: {
    type: 'manual_input', label: 'Manual Data Input', category: 'data',
    description: 'Type one or more records by hand — feed into scalers, encoders, and models for prediction',
    inputs: [], outputs: [{ name: 'dataset', type: 'dataset' }],
    config: [
      { id: 'columns', label: 'Column Names (comma-separated)', type: 'text', default: 'feature1, feature2' },
      { id: 'data', label: 'Data Rows (one row per line, comma-separated values)', type: 'textarea', default: '' },
    ],
  },
  data_sample: {
    type: 'data_sample', label: 'Data Sampling', category: 'data',
    description: 'Sample rows from dataset',
    inputs: [{ name: 'dataset', type: 'dataset' }], outputs: [{ name: 'dataset', type: 'dataset' }],
    config: [
      { id: 'n', label: 'Sample Size', type: 'number', default: 500 },
      { id: 'frac', label: 'Fraction', type: 'number', default: 0.1 },
      { id: 'random_state', label: 'Random Seed', type: 'number', default: 42 },
    ],
  },

  // ── DATA QUALITY ──────────────────────────────────────────────────────────
  imputer: {
    type: 'imputer', label: 'Missing Value Imputer', category: 'quality',
    description: 'Fill missing values using various strategies',
    inputs: [{ name: 'dataset', type: 'dataset' }], outputs: [{ name: 'dataset', type: 'dataset' }],
    config: [
      { id: 'strategy', label: 'Strategy', type: 'select', options: ['mean', 'median', 'mode', 'constant', 'knn'], default: 'mean' },
      { id: 'fill_value', label: 'Fill Value', type: 'text', default: '0' },
      { id: 'cols', label: 'Columns (comma-sep)', type: 'text', default: '' },
    ],
  },
  dup_remover: {
    type: 'dup_remover', label: 'Duplicate Remover', category: 'quality',
    description: 'Remove duplicate rows',
    inputs: [{ name: 'dataset', type: 'dataset' }], outputs: [{ name: 'dataset', type: 'dataset' }],
    config: [
      { id: 'subset', label: 'Subset Columns', type: 'text', default: '' },
      { id: 'keep', label: 'Keep', type: 'select', options: ['first', 'last', 'none'], default: 'first' },
    ],
  },
  outlier: {
    type: 'outlier', label: 'Outlier Detector', category: 'quality',
    description: 'Detect and handle outliers in selected numeric columns',
    inputs: [{ name: 'dataset', type: 'dataset' }], outputs: [{ name: 'dataset', type: 'dataset' }, { name: 'outliers', type: 'outliers' }],
    config: [
      { id: 'method', label: 'Method', type: 'select', options: ['IQR', 'Z-Score', 'Isolation Forest'], default: 'IQR' },
      { id: 'action', label: 'Action', type: 'select', options: ['remove', 'clip', 'flag'], default: 'remove' },
      { id: 'threshold', label: 'Threshold (Z-Score)', type: 'number', default: 3 },
      { id: 'cols', label: 'Columns (comma-sep, blank = all numeric)', type: 'text', default: '' },
      { id: 'col_mode', label: 'Column Mode', type: 'select', options: ['include', 'exclude'], default: 'include' },
    ],
  },
  col_rename: {
    type: 'col_rename', label: 'Column Renamer', category: 'quality',
    description: 'Rename one or more columns',
    inputs: [{ name: 'dataset', type: 'dataset' }], outputs: [{ name: 'dataset', type: 'dataset' }],
    config: [
      { id: 'mappings', label: 'Rename Mappings', type: 'col_map', default: [] },
    ],
  },
  type_conv: {
    type: 'type_conv', label: 'Type Converter', category: 'quality',
    description: 'Convert column data types',
    inputs: [{ name: 'dataset', type: 'dataset' }], outputs: [{ name: 'dataset', type: 'dataset' }],
    config: [
      { id: 'rules', label: 'Conversion Rules', type: 'textarea', default: 'col1: float\ncol2: int' },
    ],
  },
  validator: {
    type: 'validator', label: 'Data Validator', category: 'quality',
    description: 'Enforce schema and constraints',
    inputs: [{ name: 'dataset', type: 'dataset' }], outputs: [{ name: 'dataset', type: 'dataset' }, { name: 'report', type: 'report' }],
    config: [
      { id: 'schema', label: 'Schema (JSON)', type: 'textarea', default: '{"col1": "float", "col2": "str"}' },
      { id: 'strict', label: 'Strict Mode', type: 'toggle', default: false },
    ],
  },

  // ── FEATURE ENGINEERING ───────────────────────────────────────────────────
  col_selector: {
    type: 'col_selector', label: 'Column Selector', category: 'feature',
    description: 'Select or drop columns',
    inputs: [{ name: 'dataset', type: 'dataset' }], outputs: [{ name: 'dataset', type: 'dataset' }],
    config: [
      { id: 'mode', label: 'Mode', type: 'select', options: ['include', 'exclude'], default: 'include' },
      { id: 'cols', label: 'Columns', type: 'text', default: 'col1, col2, col3' },
    ],
  },
  ohe: {
    type: 'ohe', label: 'One-Hot Encoder', category: 'feature',
    description: 'Encode categorical columns as binary',
    inputs: [{ name: 'dataset', type: 'dataset' }],
    outputs: [{ name: 'dataset', type: 'dataset' }, { name: 'transformer', type: 'transformer' }],
    config: [
      { id: 'cols', label: 'Columns', type: 'text', default: '' },
      { id: 'drop', label: 'Drop First', type: 'toggle', default: false },
      { id: 'sparse', label: 'Sparse Output', type: 'toggle', default: false },
    ],
  },
  label_enc: {
    type: 'label_enc', label: 'Label Encoder', category: 'feature',
    description: 'Encode labels as integers',
    inputs: [{ name: 'dataset', type: 'dataset' }],
    outputs: [{ name: 'dataset', type: 'dataset' }, { name: 'transformer', type: 'transformer' }],
    config: [
      { id: 'cols', label: 'Columns', type: 'text', default: 'target' },
    ],
  },
  scaler: {
    type: 'scaler', label: 'Scaler', category: 'feature',
    description: 'Normalize or standardize features',
    inputs: [{ name: 'dataset', type: 'dataset' }],
    outputs: [{ name: 'dataset', type: 'dataset' }, { name: 'transformer', type: 'transformer' }],
    config: [
      { id: 'method', label: 'Method', type: 'select', options: ['StandardScaler', 'MinMaxScaler', 'RobustScaler', 'MaxAbsScaler'], default: 'StandardScaler' },
      { id: 'cols', label: 'Columns', type: 'text', default: '' },
    ],
  },
  feat_gen: {
    type: 'feat_gen', label: 'Feature Generator', category: 'feature',
    description: 'Create polynomial or interaction features',
    inputs: [{ name: 'dataset', type: 'dataset' }], outputs: [{ name: 'dataset', type: 'dataset' }],
    config: [
      { id: 'degree', label: 'Degree', type: 'number', default: 2 },
      { id: 'interaction', label: 'Interaction Only', type: 'toggle', default: false },
    ],
  },
  tfidf: {
    type: 'tfidf', label: 'Text Vectorizer', category: 'feature',
    description: 'TF-IDF or CountVectorizer for text',
    inputs: [{ name: 'dataset', type: 'dataset' }], outputs: [{ name: 'dataset', type: 'dataset' }],
    config: [
      { id: 'col', label: 'Text Column', type: 'text', default: 'text' },
      { id: 'method', label: 'Method', type: 'select', options: ['TF-IDF', 'CountVectorizer'], default: 'TF-IDF' },
      { id: 'max_features', label: 'Max Features', type: 'number', default: 1000 },
    ],
  },
  embedding: {
    type: 'embedding', label: 'Embedding Generator', category: 'feature',
    description: 'Generate embeddings for text or categories',
    inputs: [{ name: 'dataset', type: 'dataset' }], outputs: [{ name: 'dataset', type: 'dataset' }],
    config: [
      { id: 'col', label: 'Column', type: 'text', default: 'text' },
      { id: 'dim', label: 'Dimensions', type: 'number', default: 128 },
    ],
  },
  date_feat: {
    type: 'date_feat', label: 'Date Feature Extractor', category: 'feature',
    description: 'Extract year, month, day, weekday, etc.',
    inputs: [{ name: 'dataset', type: 'dataset' }], outputs: [{ name: 'dataset', type: 'dataset' }],
    config: [
      { id: 'col', label: 'Date Column', type: 'text', default: 'date' },
      { id: 'features', label: 'Extract', type: 'text', default: 'year,month,day,weekday' },
    ],
  },
  feat_imp_sel: {
    type: 'feat_imp_sel', label: 'Feature Importance Sel', category: 'feature',
    description: 'Select top features by importance score',
    inputs: [{ name: 'dataset', type: 'dataset' }], outputs: [{ name: 'dataset', type: 'dataset' }],
    config: [
      { id: 'k', label: 'Top K Features', type: 'number', default: 20 },
      { id: 'method', label: 'Method', type: 'select', options: ['chi2', 'f_classif', 'mutual_info'], default: 'f_classif' },
    ],
  },
  pca: {
    type: 'pca', label: 'PCA', category: 'feature',
    description: 'Principal Component Analysis',
    inputs: [{ name: 'dataset', type: 'dataset' }], outputs: [{ name: 'dataset', type: 'dataset' }],
    config: [
      { id: 'n_components', label: 'Components', type: 'number', default: 10 },
      { id: 'whiten', label: 'Whiten', type: 'toggle', default: false },
    ],
  },
  str_split: {
    type: 'str_split', label: 'String Splitter', category: 'feature',
    description: 'Split a string column by a configurable separator',
    inputs: [{ name: 'dataset', type: 'dataset' }], outputs: [{ name: 'dataset', type: 'dataset' }],
    config: [
      { id: 'col', label: 'Column', type: 'text', default: 'text' },
      { id: 'sep', label: 'Separator', type: 'select', options: ['space', 'tab', 'comma', 'hyphen', 'pipe', 'semicolon'], default: 'space' },
      { id: 'expand', label: 'Expand to Columns', type: 'toggle', default: true },
      { id: 'prefix', label: 'Column Prefix', type: 'text', default: 'part' },
    ],
  },

  // ── DATA BALANCING ────────────────────────────────────────────────────────
  smote: {
    type: 'smote', label: 'SMOTE', category: 'balance',
    description: 'Oversample minority class synthetically',
    inputs: [{ name: 'dataset', type: 'dataset' }], outputs: [{ name: 'dataset', type: 'dataset' }],
    config: [
      { id: 'k_neighbors', label: 'K Neighbors', type: 'number', default: 5 },
      { id: 'random_state', label: 'Random Seed', type: 'number', default: 42 },
    ],
  },
  undersample: {
    type: 'undersample', label: 'Undersampling', category: 'balance',
    description: 'Reduce majority class samples',
    inputs: [{ name: 'dataset', type: 'dataset' }], outputs: [{ name: 'dataset', type: 'dataset' }],
    config: [
      { id: 'strategy', label: 'Strategy', type: 'select', options: ['random', 'tomek', 'enn'], default: 'random' },
      { id: 'ratio', label: 'Ratio', type: 'number', default: 1.0 },
    ],
  },
  oversample: {
    type: 'oversample', label: 'Oversampling', category: 'balance',
    description: 'Duplicate minority class samples',
    inputs: [{ name: 'dataset', type: 'dataset' }], outputs: [{ name: 'dataset', type: 'dataset' }],
    config: [
      { id: 'strategy', label: 'Strategy', type: 'select', options: ['random', 'adasyn'], default: 'random' },
    ],
  },
  class_weight: {
    type: 'class_weight', label: 'Class Weight Adjuster', category: 'balance',
    description: 'Balance via class weights',
    inputs: [{ name: 'dataset', type: 'dataset' }], outputs: [{ name: 'dataset', type: 'dataset' }],
    config: [
      { id: 'mode', label: 'Mode', type: 'select', options: ['balanced', 'auto', 'custom'], default: 'balanced' },
    ],
  },

  // ── DATA SPLIT ────────────────────────────────────────────────────────────
  train_test: {
    type: 'train_test', label: 'Train / Test Split', category: 'split',
    description: 'Split into training and test sets — outputs X/y separately',
    inputs: [{ name: 'dataset', type: 'dataset' }],
    outputs: [
      { name: 'X_train', type: 'X_train' },
      { name: 'y_train', type: 'y_train' },
      { name: 'X_test',  type: 'X_test'  },
      { name: 'y_test',  type: 'y_test'  },
    ],
    config: [
      { id: 'test_size', label: 'Test Size', type: 'number', default: 0.2 },
      { id: 'random_state', label: 'Random Seed', type: 'number', default: 42 },
      { id: 'stratify', label: 'Stratify', type: 'toggle', default: false },
      { id: 'target_col', label: 'Target Column (blank = auto)', type: 'text', default: '' },
    ],
  },
  train_val_test: {
    type: 'train_val_test', label: 'Train/Val/Test Split', category: 'split',
    description: 'Three-way dataset split — outputs X/y separately',
    inputs: [{ name: 'dataset', type: 'dataset' }],
    outputs: [
      { name: 'X_train', type: 'X_train' },
      { name: 'y_train', type: 'y_train' },
      { name: 'X_val',   type: 'X_val'   },
      { name: 'y_val',   type: 'y_val'   },
      { name: 'X_test',  type: 'X_test'  },
      { name: 'y_test',  type: 'y_test'  },
    ],
    config: [
      { id: 'val_size', label: 'Val Size', type: 'number', default: 0.1 },
      { id: 'test_size', label: 'Test Size', type: 'number', default: 0.2 },
      { id: 'random_state', label: 'Random Seed', type: 'number', default: 42 },
      { id: 'target_col', label: 'Target Column (blank = auto)', type: 'text', default: '' },
    ],
  },
  cv_split: {
    type: 'cv_split', label: 'Cross-Validation Split', category: 'split',
    description: 'K-Fold split — returns one fold as X/y train+test, ready for model nodes',
    inputs: [{ name: 'dataset', type: 'dataset' }],
    outputs: [
      { name: 'X_train', type: 'X_train' },
      { name: 'y_train', type: 'y_train' },
      { name: 'X_test',  type: 'X_test'  },
      { name: 'y_test',  type: 'y_test'  },
    ],
    config: [
      { id: 'target_col', label: 'Target Column (blank = auto)', type: 'text', default: '' },
      { id: 'k', label: 'K Folds', type: 'number', default: 5, min: 2 },
      { id: 'fold_index', label: 'Test Fold Index (0 to K-1)', type: 'number', default: 0, min: 0 },
      { id: 'method', label: 'Method', type: 'select', options: ['StratifiedKFold', 'KFold'], default: 'StratifiedKFold' },
      { id: 'shuffle', label: 'Shuffle', type: 'toggle', default: true },
      { id: 'random_state', label: 'Random Seed', type: 'number', default: 42 },
    ],
  },
  dataset_to_xy: {
    type: 'dataset_to_xy', label: 'Dataset → X, y', category: 'split',
    description: 'Extract feature matrix X and target vector y from a dataset by column name — preserves row index for later joining',
    inputs: [{ name: 'dataset', type: 'dataset' }],
    outputs: [
      { name: 'X_train', type: 'X_train' },
      { name: 'y_train', type: 'y_train' },
    ],
    config: [
      { id: 'target_col', label: 'Target Column (blank = auto-detect last)', type: 'text', default: '' },
    ],
  },
  xy_to_dataset: {
    type: 'xy_to_dataset', label: 'X, y → Dataset', category: 'split',
    description: 'Recombine feature matrix X and target vector y into a single dataset using index alignment',
    inputs: [
      { name: 'X_train', type: 'X_train' },
      { name: 'y_train', type: 'y_train' },
    ],
    outputs: [{ name: 'dataset', type: 'dataset' }],
    config: [
      { id: 'target_col', label: 'Target Column Name', type: 'text', default: 'target' },
    ],
  },

  // ── MODELS ────────────────────────────────────────────────────────────────
  lin_reg: {
    type: 'lin_reg', label: 'Linear Regression', category: 'model',
    description: 'Ordinary least squares regression',
    inputs: [
      { name: 'X_train',   type: 'X_train'  },
      { name: 'y_train',   type: 'y_train'  },
      { name: 'X_val',     type: 'X_val'    },
      { name: 'y_val',     type: 'y_val'    },
      { name: 'hp_config', type: 'hpconfig' },
    ],
    outputs: [{ name: 'model', type: 'model' }],
    config: [
      { id: 'fit_intercept', label: 'Fit Intercept', type: 'toggle', default: true },
    ],
  },
  log_reg: {
    type: 'log_reg', label: 'Logistic Regression', category: 'model',
    description: 'Binary or multiclass classification',
    inputs: [
      { name: 'X_train',   type: 'X_train'  },
      { name: 'y_train',   type: 'y_train'  },
      { name: 'X_val',     type: 'X_val'    },
      { name: 'y_val',     type: 'y_val'    },
      { name: 'hp_config', type: 'hpconfig' },
    ],
    outputs: [{ name: 'model', type: 'model' }],
    config: [
      { id: 'C', label: 'C (Regularization)', type: 'number', default: 1.0 },
      { id: 'solver', label: 'Solver', type: 'select', options: ['lbfgs', 'saga', 'liblinear'], default: 'lbfgs' },
      { id: 'max_iter', label: 'Max Iterations', type: 'number', default: 100 },
    ],
  },
  dtree: {
    type: 'dtree', label: 'Decision Tree', category: 'model',
    description: 'Decision tree classifier/regressor',
    inputs: [
      { name: 'X_train',   type: 'X_train'  },
      { name: 'y_train',   type: 'y_train'  },
      { name: 'X_val',     type: 'X_val'    },
      { name: 'y_val',     type: 'y_val'    },
      { name: 'hp_config', type: 'hpconfig' },
    ],
    outputs: [{ name: 'model', type: 'model' }],
    config: [
      { id: 'max_depth', label: 'Max Depth', type: 'number', default: 5 },
      { id: 'min_samples_split', label: 'Min Samples Split', type: 'number', default: 2 },
      { id: 'criterion', label: 'Criterion', type: 'select', options: ['gini', 'entropy'], default: 'gini' },
    ],
  },
  rf: {
    type: 'rf', label: 'Random Forest', category: 'model',
    description: 'Ensemble of decision trees',
    inputs: [
      { name: 'X_train',   type: 'X_train'  },
      { name: 'y_train',   type: 'y_train'  },
      { name: 'X_val',     type: 'X_val'    },
      { name: 'y_val',     type: 'y_val'    },
      { name: 'hp_config', type: 'hpconfig' },
    ],
    outputs: [{ name: 'model', type: 'model' }],
    config: [
      { id: 'n_estimators', label: 'Estimators', type: 'number', default: 100 },
      { id: 'max_depth', label: 'Max Depth', type: 'number', default: 10 },
      { id: 'max_features', label: 'Max Features', type: 'select', options: ['sqrt', 'log2', 'auto'], default: 'sqrt' },
      { id: 'random_state', label: 'Random Seed', type: 'number', default: 42 },
    ],
  },
  xgb: {
    type: 'xgb', label: 'XGBoost', category: 'model',
    description: 'Gradient boosting — high performance',
    inputs: [
      { name: 'X_train',   type: 'X_train'  },
      { name: 'y_train',   type: 'y_train'  },
      { name: 'X_val',     type: 'X_val'    },
      { name: 'y_val',     type: 'y_val'    },
      { name: 'hp_config', type: 'hpconfig' },
    ],
    outputs: [{ name: 'model', type: 'model' }],
    config: [
      { id: 'n_estimators', label: 'Estimators', type: 'number', default: 100 },
      { id: 'learning_rate', label: 'Learning Rate', type: 'number', default: 0.1 },
      { id: 'max_depth', label: 'Max Depth', type: 'number', default: 6 },
      { id: 'subsample', label: 'Subsample', type: 'number', default: 0.8 },
    ],
  },
  svm: {
    type: 'svm', label: 'Support Vector Machine', category: 'model',
    description: 'SVM for classification or regression',
    inputs: [
      { name: 'X_train',   type: 'X_train'  },
      { name: 'y_train',   type: 'y_train'  },
      { name: 'X_val',     type: 'X_val'    },
      { name: 'y_val',     type: 'y_val'    },
      { name: 'hp_config', type: 'hpconfig' },
    ],
    outputs: [{ name: 'model', type: 'model' }],
    config: [
      { id: 'C', label: 'C', type: 'number', default: 1.0 },
      { id: 'kernel', label: 'Kernel', type: 'select', options: ['rbf', 'linear', 'poly', 'sigmoid'], default: 'rbf' },
      { id: 'gamma', label: 'Gamma', type: 'select', options: ['scale', 'auto'], default: 'scale' },
    ],
  },
  knn: {
    type: 'knn', label: 'KNN', category: 'model',
    description: 'K-Nearest Neighbors',
    inputs: [
      { name: 'X_train',   type: 'X_train'  },
      { name: 'y_train',   type: 'y_train'  },
      { name: 'X_val',     type: 'X_val'    },
      { name: 'y_val',     type: 'y_val'    },
      { name: 'hp_config', type: 'hpconfig' },
    ],
    outputs: [{ name: 'model', type: 'model' }],
    config: [
      { id: 'n_neighbors', label: 'Neighbors', type: 'number', default: 5 },
      { id: 'metric', label: 'Metric', type: 'select', options: ['euclidean', 'manhattan', 'cosine'], default: 'euclidean' },
      { id: 'weights', label: 'Weights', type: 'select', options: ['uniform', 'distance'], default: 'uniform' },
    ],
  },
  nb: {
    type: 'nb', label: 'Naive Bayes', category: 'model',
    description: 'Probabilistic classifier',
    inputs: [
      { name: 'X_train',   type: 'X_train'  },
      { name: 'y_train',   type: 'y_train'  },
      { name: 'X_val',     type: 'X_val'    },
      { name: 'y_val',     type: 'y_val'    },
      { name: 'hp_config', type: 'hpconfig' },
    ],
    outputs: [{ name: 'model', type: 'model' }],
    config: [
      { id: 'variant', label: 'Variant', type: 'select', options: ['GaussianNB', 'MultinomialNB', 'BernoulliNB'], default: 'GaussianNB' },
      { id: 'var_smoothing', label: 'Var Smoothing', type: 'number', default: 1e-9 },
    ],
  },
  mlp: {
    type: 'mlp', label: 'Neural Network (MLP)', category: 'model',
    description: 'Multilayer perceptron',
    inputs: [
      { name: 'X_train',   type: 'X_train'  },
      { name: 'y_train',   type: 'y_train'  },
      { name: 'X_val',     type: 'X_val'    },
      { name: 'y_val',     type: 'y_val'    },
      { name: 'hp_config', type: 'hpconfig' },
    ],
    outputs: [{ name: 'model', type: 'model' }],
    config: [
      { id: 'layers', label: 'Hidden Layers', type: 'text', default: '128, 64, 32' },
      { id: 'activation', label: 'Activation', type: 'select', options: ['relu', 'tanh', 'sigmoid'], default: 'relu' },
      { id: 'lr', label: 'Learning Rate', type: 'number', default: 0.001 },
      { id: 'epochs', label: 'Epochs', type: 'number', default: 100 },
      { id: 'batch_size', label: 'Batch Size', type: 'number', default: 32 },
    ],
  },

  // ── REGRESSION MODELS ────────────────────────────────────────────────────
  ridge: {
    type: 'ridge', label: 'Ridge Regression', category: 'model',
    description: 'L2-regularized linear regression',
    inputs: [
      { name: 'X_train',   type: 'X_train'  },
      { name: 'y_train',   type: 'y_train'  },
      { name: 'X_val',     type: 'X_val'    },
      { name: 'y_val',     type: 'y_val'    },
      { name: 'hp_config', type: 'hpconfig' },
    ],
    outputs: [{ name: 'model', type: 'model' }],
    config: [
      { id: 'alpha', label: 'Alpha (Regularization)', type: 'number', default: 1.0 },
      { id: 'fit_intercept', label: 'Fit Intercept', type: 'toggle', default: true },
    ],
  },
  lasso: {
    type: 'lasso', label: 'Lasso Regression', category: 'model',
    description: 'L1-regularized regression — performs feature selection',
    inputs: [
      { name: 'X_train',   type: 'X_train'  },
      { name: 'y_train',   type: 'y_train'  },
      { name: 'X_val',     type: 'X_val'    },
      { name: 'y_val',     type: 'y_val'    },
      { name: 'hp_config', type: 'hpconfig' },
    ],
    outputs: [{ name: 'model', type: 'model' }],
    config: [
      { id: 'alpha', label: 'Alpha (Regularization)', type: 'number', default: 1.0 },
      { id: 'max_iter', label: 'Max Iterations', type: 'number', default: 1000 },
    ],
  },
  rf_reg: {
    type: 'rf_reg', label: 'Random Forest Regressor', category: 'model',
    description: 'Ensemble of decision trees for regression',
    inputs: [
      { name: 'X_train',   type: 'X_train'  },
      { name: 'y_train',   type: 'y_train'  },
      { name: 'X_val',     type: 'X_val'    },
      { name: 'y_val',     type: 'y_val'    },
      { name: 'hp_config', type: 'hpconfig' },
    ],
    outputs: [{ name: 'model', type: 'model' }],
    config: [
      { id: 'n_estimators', label: 'Estimators', type: 'number', default: 100 },
      { id: 'max_depth', label: 'Max Depth', type: 'number', default: 10 },
      { id: 'max_features', label: 'Max Features', type: 'select', options: ['sqrt', 'log2', 'auto'], default: 'sqrt' },
      { id: 'random_state', label: 'Random Seed', type: 'number', default: 42 },
    ],
  },
  xgb_reg: {
    type: 'xgb_reg', label: 'XGBoost Regressor', category: 'model',
    description: 'Gradient boosting for regression — high performance',
    inputs: [
      { name: 'X_train',   type: 'X_train'  },
      { name: 'y_train',   type: 'y_train'  },
      { name: 'X_val',     type: 'X_val'    },
      { name: 'y_val',     type: 'y_val'    },
      { name: 'hp_config', type: 'hpconfig' },
    ],
    outputs: [{ name: 'model', type: 'model' }],
    config: [
      { id: 'n_estimators', label: 'Estimators', type: 'number', default: 100 },
      { id: 'learning_rate', label: 'Learning Rate', type: 'number', default: 0.1 },
      { id: 'max_depth', label: 'Max Depth', type: 'number', default: 6 },
      { id: 'subsample', label: 'Subsample', type: 'number', default: 0.8 },
    ],
  },
  dtree_reg: {
    type: 'dtree_reg', label: 'Decision Tree Regressor', category: 'model',
    description: 'Decision tree for regression tasks',
    inputs: [
      { name: 'X_train',   type: 'X_train'  },
      { name: 'y_train',   type: 'y_train'  },
      { name: 'X_val',     type: 'X_val'    },
      { name: 'y_val',     type: 'y_val'    },
      { name: 'hp_config', type: 'hpconfig' },
    ],
    outputs: [{ name: 'model', type: 'model' }],
    config: [
      { id: 'max_depth', label: 'Max Depth', type: 'number', default: 5 },
      { id: 'min_samples_split', label: 'Min Samples Split', type: 'number', default: 2 },
      { id: 'criterion', label: 'Criterion', type: 'select', options: ['squared_error', 'absolute_error', 'friedman_mse'], default: 'squared_error' },
    ],
  },
  svr: {
    type: 'svr', label: 'Support Vector Regressor', category: 'model',
    description: 'SVR for regression tasks',
    inputs: [
      { name: 'X_train',   type: 'X_train'  },
      { name: 'y_train',   type: 'y_train'  },
      { name: 'X_val',     type: 'X_val'    },
      { name: 'y_val',     type: 'y_val'    },
      { name: 'hp_config', type: 'hpconfig' },
    ],
    outputs: [{ name: 'model', type: 'model' }],
    config: [
      { id: 'C', label: 'C', type: 'number', default: 1.0 },
      { id: 'kernel', label: 'Kernel', type: 'select', options: ['rbf', 'linear', 'poly', 'sigmoid'], default: 'rbf' },
      { id: 'epsilon', label: 'Epsilon', type: 'number', default: 0.1 },
      { id: 'gamma', label: 'Gamma', type: 'select', options: ['scale', 'auto'], default: 'scale' },
    ],
  },
  knn_reg: {
    type: 'knn_reg', label: 'KNN Regressor', category: 'model',
    description: 'K-Nearest Neighbors for regression',
    inputs: [
      { name: 'X_train',   type: 'X_train'  },
      { name: 'y_train',   type: 'y_train'  },
      { name: 'X_val',     type: 'X_val'    },
      { name: 'y_val',     type: 'y_val'    },
      { name: 'hp_config', type: 'hpconfig' },
    ],
    outputs: [{ name: 'model', type: 'model' }],
    config: [
      { id: 'n_neighbors', label: 'Neighbors', type: 'number', default: 5 },
      { id: 'metric', label: 'Metric', type: 'select', options: ['euclidean', 'manhattan', 'cosine'], default: 'euclidean' },
      { id: 'weights', label: 'Weights', type: 'select', options: ['uniform', 'distance'], default: 'uniform' },
    ],
  },
  mlp_reg: {
    type: 'mlp_reg', label: 'Neural Network Regressor', category: 'model',
    description: 'Multilayer perceptron for regression',
    inputs: [
      { name: 'X_train',   type: 'X_train'  },
      { name: 'y_train',   type: 'y_train'  },
      { name: 'X_val',     type: 'X_val'    },
      { name: 'y_val',     type: 'y_val'    },
      { name: 'hp_config', type: 'hpconfig' },
    ],
    outputs: [{ name: 'model', type: 'model' }],
    config: [
      { id: 'layers', label: 'Hidden Layers', type: 'text', default: '128, 64, 32' },
      { id: 'activation', label: 'Activation', type: 'select', options: ['relu', 'tanh', 'sigmoid'], default: 'relu' },
      { id: 'lr', label: 'Learning Rate', type: 'number', default: 0.001 },
      { id: 'epochs', label: 'Epochs', type: 'number', default: 100 },
      { id: 'batch_size', label: 'Batch Size', type: 'number', default: 32 },
    ],
  },
  gb_reg: {
    type: 'gb_reg', label: 'Gradient Boosting Regressor', category: 'model',
    description: 'Gradient boosting ensemble for regression (scikit-learn)',
    inputs: [
      { name: 'X_train',   type: 'X_train'  },
      { name: 'y_train',   type: 'y_train'  },
      { name: 'X_val',     type: 'X_val'    },
      { name: 'y_val',     type: 'y_val'    },
      { name: 'hp_config', type: 'hpconfig' },
    ],
    outputs: [{ name: 'model', type: 'model' }],
    config: [
      { id: 'n_estimators', label: 'Estimators', type: 'number', default: 100 },
      { id: 'learning_rate', label: 'Learning Rate', type: 'number', default: 0.1 },
      { id: 'max_depth', label: 'Max Depth', type: 'number', default: 3 },
      { id: 'subsample', label: 'Subsample', type: 'number', default: 1.0 },
      { id: 'random_state', label: 'Random Seed', type: 'number', default: 42 },
    ],
  },

  // ── ADVANCED ──────────────────────────────────────────────────────────────
  automl: {
    type: 'automl', label: 'AutoML Search', category: 'advanced',
    description: 'Auto-select best model and hyperparams',
    inputs: [
      { name: 'X_train', type: 'X_train' },
      { name: 'y_train', type: 'y_train' },
      { name: 'X_val',   type: 'X_val'   },
      { name: 'y_val',   type: 'y_val'   },
    ],
    outputs: [{ name: 'model', type: 'model' }, { name: 'report', type: 'report' }],
    config: [
      { id: 'time_budget', label: 'Time Budget (s)', type: 'number', default: 60 },
      { id: 'metric', label: 'Optimize', type: 'select', options: ['accuracy', 'f1', 'roc_auc', 'rmse', 'r2'], default: 'accuracy' },
      { id: 'n_trials', label: 'Trials', type: 'number', default: 50 },
    ],
  },
  hp_tune: {
    type: 'hp_tune', label: 'HP Tuning Config', category: 'advanced',
    description: 'Emit a hyperparameter search config to connect to any model node',
    inputs: [],
    outputs: [{ name: 'hp_config', type: 'hpconfig' }],
    config: [
      { id: 'method', label: 'Method', type: 'select', options: ['Grid', 'Random', 'Bayesian'], default: 'Random' },
      { id: 'scoring', label: 'Scoring Metric', type: 'select', options: ['accuracy', 'f1_weighted', 'f1_macro', 'roc_auc', 'r2', 'neg_root_mean_squared_error', 'neg_mean_absolute_error'], default: 'accuracy' },
      { id: 'n_iter', label: 'Iterations (Random/Bayesian only)', type: 'number', default: 25, min: 1 },
      { id: 'cv', label: 'CV Folds', type: 'number', default: 5, min: 2 },
      { id: 'n_jobs', label: 'Parallel Jobs (-1 = all cores)', type: 'number', default: -1, min: -1 },
      { id: 'params', label: 'Parameter Grid', type: 'hp_params', default: [] },
    ],
  },
  pipeline_wrap: {
    type: 'pipeline_wrap', label: 'Pipeline Wrapper', category: 'advanced',
    description: 'Wrap preprocessing + model into a pipeline',
    inputs: [{ name: 'dataset', type: 'dataset' }, { name: 'model', type: 'model' }],
    outputs: [{ name: 'pipeline', type: 'pipeline' }],
    config: [
      { id: 'memory', label: 'Cache Pipeline', type: 'toggle', default: false },
    ],
  },
  custom_code: {
    type: 'custom_code', label: 'Custom Code Node', category: 'advanced',
    description: 'Execute custom Python snippet',
    inputs: [{ name: 'dataset', type: 'dataset' }], outputs: [{ name: 'dataset', type: 'dataset' }],
    config: [
      { id: 'code', label: 'Python Code', type: 'textarea', default: '# df is your DataFrame\ndf["new_col"] = df["col1"] * 2\nreturn df', mono: true },
    ],
  },

  // ── ENSEMBLE ──────────────────────────────────────────────────────────────
  voting: {
    type: 'voting', label: 'Voting Classifier', category: 'ensemble',
    description: 'Combine up to 5 models by voting — connect at least 2, unused inputs are ignored',
    inputs: [
      { name: 'model_1', type: 'model' },
      { name: 'model_2', type: 'model' },
      { name: 'model_3', type: 'model' },
      { name: 'model_4', type: 'model' },
      { name: 'model_5', type: 'model' },
    ],
    outputs: [{ name: 'model', type: 'model' }],
    config: [
      { id: 'voting', label: 'Voting', type: 'select', options: ['hard', 'soft'], default: 'soft' },
      { id: 'weights', label: 'Weights (comma-sep, one per connected model)', type: 'text', default: '' },
    ],
  },
  stacking: {
    type: 'stacking', label: 'Stacking Ensemble', category: 'ensemble',
    description: 'Stack up to 5 base models with a meta-learner — connect at least 2 models plus X_train and y_train to fit the meta-learner',
    inputs: [
      { name: 'model_1', type: 'model' },
      { name: 'model_2', type: 'model' },
      { name: 'model_3', type: 'model' },
      { name: 'model_4', type: 'model' },
      { name: 'model_5', type: 'model' },
      { name: 'X_train', type: 'X_train' },
      { name: 'y_train', type: 'y_train' },
    ],
    outputs: [{ name: 'model', type: 'model' }],
    config: [
      { id: 'meta', label: 'Meta Learner', type: 'select', options: ['LogisticRegression', 'LinearRegression'], default: 'LogisticRegression' },
      { id: 'cv', label: 'CV Folds', type: 'number', default: 5 },
    ],
  },
  blending: {
    type: 'blending', label: 'Blending Node', category: 'ensemble',
    description: 'Blend predictions from up to 5 models — connect at least 2, unused inputs are ignored',
    inputs: [
      { name: 'model_1', type: 'model' },
      { name: 'model_2', type: 'model' },
      { name: 'model_3', type: 'model' },
      { name: 'model_4', type: 'model' },
      { name: 'model_5', type: 'model' },
    ],
    outputs: [{ name: 'model', type: 'model' }],
    config: [
      { id: 'method', label: 'Method', type: 'select', options: ['mean', 'weighted_mean', 'rank_avg'], default: 'mean' },
    ],
  },

  // ── EVALUATION ────────────────────────────────────────────────────────────
  metrics: {
    type: 'metrics', label: 'Metrics Node', category: 'eval',
    description: 'Compute classification or regression metrics',
    inputs: [
      { name: 'model',  type: 'model'  },
      { name: 'X_test', type: 'X_test' },
      { name: 'y_test', type: 'y_test' },
    ],
    outputs: [{ name: 'report', type: 'report' }],
    config: [
      { id: 'task', label: 'Task', type: 'select', options: ['classification', 'regression'], default: 'classification' },
      { id: 'average', label: 'Average', type: 'select', options: ['micro', 'macro', 'weighted'], default: 'weighted' },
    ],
  },
  conf_matrix: {
    type: 'conf_matrix', label: 'Confusion Matrix', category: 'eval',
    description: 'Visualize prediction confusion matrix',
    inputs: [
      { name: 'model',  type: 'model'  },
      { name: 'X_test', type: 'X_test' },
      { name: 'y_test', type: 'y_test' },
    ],
    outputs: [{ name: 'plot', type: 'plot' }],
    config: [
      { id: 'normalize', label: 'Normalize', type: 'select', options: ['true', 'pred', 'all', 'none'], default: 'none' },
      { id: 'cmap', label: 'Colormap', type: 'text', default: 'Blues' },
    ],
  },
  roc_curve: {
    type: 'roc_curve', label: 'ROC Curve', category: 'eval',
    description: 'Plot ROC-AUC curve',
    inputs: [
      { name: 'model',  type: 'model'  },
      { name: 'X_test', type: 'X_test' },
      { name: 'y_test', type: 'y_test' },
    ],
    outputs: [{ name: 'plot', type: 'plot' }],
    config: [
      { id: 'multi_class', label: 'Multi-class Strategy', type: 'select', options: ['ovr', 'ovo'], default: 'ovr' },
    ],
  },
  feat_imp_viz: {
    type: 'feat_imp_viz', label: 'Feature Importance Viz', category: 'eval',
    description: 'Visualize feature importances',
    inputs: [{ name: 'model', type: 'model' }], outputs: [{ name: 'plot', type: 'plot' }],
    config: [
      { id: 'top_n', label: 'Top N Features', type: 'number', default: 20 },
    ],
  },
  residual: {
    type: 'residual', label: 'Residual Analysis', category: 'eval',
    description: 'Analyze regression residuals',
    inputs: [
      { name: 'model',  type: 'model'  },
      { name: 'X_test', type: 'X_test' },
      { name: 'y_test', type: 'y_test' },
    ],
    outputs: [{ name: 'plot', type: 'plot' }],
    config: [],
  },
  df_info: {
    type: 'df_info', label: 'DataFrame Info', category: 'eval',
    description: 'Inspect shape, types, missing values, duplicates, and per-column statistics',
    inputs: [{ name: 'dataset', type: 'dataset' }],
    outputs: [{ name: 'dataset', type: 'dataset' }],
    config: [
      { id: 'max_unique', label: 'Max Unique Values to Show', type: 'number', default: 10, min: 1 },
    ],
  },
  data_viz: {
    type: 'data_viz', label: 'Data Visualizer', category: 'eval',
    description: 'Plot dataset columns with bar, histogram, line, scatter, pie, box, violin, or heatmap charts',
    inputs: [{ name: 'dataset', type: 'dataset' }],
    outputs: [{ name: 'plot', type: 'plot' }],
    config: [
      { id: 'chart_type', label: 'Chart Type', type: 'select', options: ['Histogram', 'Bar', 'Line', 'Scatter', 'Pie', 'Box', 'Violin', 'Heatmap'], default: 'Histogram' },
      { id: 'x_col', label: 'X Column', type: 'text', default: '' },
      { id: 'y_col', label: 'Y Column', type: 'text', default: '' },
      { id: 'col', label: 'Column (Histogram / Pie)', type: 'text', default: '' },
      { id: 'hue', label: 'Hue Column (optional)', type: 'text', default: '' },
      { id: 'bins', label: 'Bins (Histogram)', type: 'number', default: 30, min: 5 },
      { id: 'title', label: 'Title (optional)', type: 'text', default: '' },
      { id: 'palette', label: 'Palette', type: 'select', options: ['viridis', 'coolwarm', 'plasma', 'Set2', 'husl', 'tab10'], default: 'viridis' },
    ],
  },
  corr_check: {
    type: 'corr_check', label: 'Correlation Check', category: 'eval',
    description: 'Visualize feature correlation matrix or pairwise scatter between two columns',
    inputs: [{ name: 'dataset', type: 'dataset' }],
    outputs: [{ name: 'plot', type: 'plot' }],
    config: [
      { id: 'mode', label: 'Mode', type: 'select', options: ['Matrix', 'Pairwise'], default: 'Matrix' },
      { id: 'method', label: 'Method', type: 'select', options: ['pearson', 'spearman', 'kendall'], default: 'pearson' },
      { id: 'col1', label: 'Column 1 (Pairwise)', type: 'text', default: '' },
      { id: 'col2', label: 'Column 2 (Pairwise)', type: 'text', default: '' },
      { id: 'top_n', label: 'Top N Features (Matrix)', type: 'number', default: 20, min: 2 },
      { id: 'cmap', label: 'Colormap', type: 'text', default: 'coolwarm' },
    ],
  },
  class_dist: {
    type: 'class_dist', label: 'Class Distribution', category: 'eval',
    description: 'Check class balance in the target column',
    inputs: [{ name: 'dataset', type: 'dataset' }],
    outputs: [{ name: 'plot', type: 'plot' }],
    config: [
      { id: 'target_col', label: 'Target Column (blank = auto)', type: 'text', default: '' },
      { id: 'show_percent', label: 'Show Percentages', type: 'toggle', default: true },
      { id: 'palette', label: 'Palette', type: 'select', options: ['viridis', 'Set2', 'husl', 'tab10', 'pastel'], default: 'Set2' },
    ],
  },

  // ── INTERPRETABILITY ──────────────────────────────────────────────────────
  shap: {
    type: 'shap', label: 'SHAP Explainer', category: 'interp',
    description: 'SHAP-based model explanations',
    inputs: [{ name: 'model', type: 'model' }, { name: 'X_test', type: 'X_test' }],
    outputs: [{ name: 'report', type: 'report' }],
    config: [
      { id: 'plot', label: 'Plot Type', type: 'select', options: ['summary', 'bar', 'waterfall', 'beeswarm'], default: 'summary' },
      { id: 'n_samples', label: 'Samples', type: 'number', default: 100 },
    ],
  },
  lime: {
    type: 'lime', label: 'LIME Explainer', category: 'interp',
    description: 'Local interpretable explanations',
    inputs: [{ name: 'model', type: 'model' }, { name: 'X_test', type: 'X_test' }],
    outputs: [{ name: 'report', type: 'report' }],
    config: [
      { id: 'n_features', label: 'Top Features', type: 'number', default: 10 },
      { id: 'mode', label: 'Mode', type: 'select', options: ['classification', 'regression'], default: 'classification' },
    ],
  },
  debugger: {
    type: 'debugger', label: 'Model Debugger', category: 'interp',
    description: 'Diagnose model issues and errors',
    inputs: [
      { name: 'model',  type: 'model'  },
      { name: 'X_test', type: 'X_test' },
      { name: 'y_test', type: 'y_test' },
    ],
    outputs: [{ name: 'report', type: 'report' }],
    config: [],
  },

  // ── DEPLOYMENT ────────────────────────────────────────────────────────────
  predict: {
    type: 'predict', label: 'Prediction Node', category: 'deploy',
    description: 'Batch prediction on new data',
    inputs: [{ name: 'model', type: 'model' }, { name: 'dataset', type: 'dataset' }],
    outputs: [{ name: 'predictions', type: 'predictions' }],
    config: [
      { id: 'output_col', label: 'Output Column', type: 'text', default: 'y_pred' },
      { id: 'proba', label: 'Return Probabilities', type: 'toggle', default: false },
    ],
  },
  api_gen: {
    type: 'api_gen', label: 'API Generator', category: 'deploy',
    description: 'Expose model as REST API endpoint',
    inputs: [{ name: 'model', type: 'model' }], outputs: [{ name: 'endpoint', type: 'endpoint' }],
    config: [
      { id: 'host', label: 'Host', type: 'text', default: '0.0.0.0' },
      { id: 'port', label: 'Port', type: 'number', default: 8000 },
      { id: 'framework', label: 'Framework', type: 'select', options: ['FastAPI', 'Flask'], default: 'FastAPI' },
    ],
  },
  csv_export: {
    type: 'csv_export', label: 'CSV Export', category: 'deploy',
    description: 'Save dataset to CSV file',
    inputs: [{ name: 'dataset', type: 'dataset' }], outputs: [],
    config: [
      { id: 'path', label: 'Output Path', type: 'text', default: 'output.csv' },
      { id: 'index', label: 'Include Index', type: 'toggle', default: false },
    ],
  },
  model_loader: {
    type: 'model_loader', label: 'Model Loader', category: 'deploy',
    description: 'Load a saved model from disk and run predictions on the connected dataset',
    inputs: [{ name: 'dataset', type: 'dataset' }],
    outputs: [{ name: 'predictions', type: 'predictions' }],
    config: [
      { id: 'path', label: 'Model File Path', type: 'text', default: 'model.pkl' },
      { id: 'output_col', label: 'Output Column Name', type: 'text', default: 'y_pred' },
      { id: 'proba', label: 'Return Probabilities', type: 'toggle', default: false },
    ],
  },
  model_saver: {
    type: 'model_saver', label: 'Model Saver', category: 'deploy',
    description: 'Serialize model with pickle/joblib',
    inputs: [{ name: 'model', type: 'model' }], outputs: [],
    config: [
      { id: 'path', label: 'Save Path', type: 'text', default: 'model.pkl' },
      { id: 'format', label: 'Format', type: 'select', options: ['joblib', 'pickle'], default: 'joblib' },
    ],
  },
  pred_print: {
    type: 'pred_print', label: 'Prediction Printer', category: 'deploy',
    description: 'Display prediction values from a Prediction Node — shows each record\'s predicted value in the preview tab',
    inputs: [{ name: 'predictions', type: 'predictions' }],
    outputs: [],
    config: [
      { id: 'pred_col', label: 'Prediction Column Name', type: 'text', default: 'y_pred' },
      { id: 'show_input', label: 'Show Input Features Too', type: 'toggle', default: false },
    ],
  },
  report_gen: {
    type: 'report_gen', label: 'Report Generator', category: 'deploy',
    description: 'Generate PDF/HTML/Jupyter summary report',
    inputs: [{ name: 'report', type: 'report' }], outputs: [],
    config: [
      { id: 'format', label: 'Format', type: 'select', options: ['HTML', 'PDF', 'Jupyter'], default: 'HTML' },
      { id: 'path', label: 'Output Path', type: 'text', default: 'report.html' },
    ],
  },
  transformer_save: {
    type: 'transformer_save', label: 'Transformer Save', category: 'deploy',
    description: 'Serialize a fitted scaler or encoder to disk for reuse',
    inputs: [{ name: 'transformer', type: 'transformer' }, { name: 'dataset', type: 'dataset' }],
    outputs: [{ name: 'dataset', type: 'dataset' }],
    config: [
      { id: 'path', label: 'Save Path (inside ~/.athena/transformers/)', type: 'text', default: 'transformer.pkl' },
    ],
  },
  transformer_load: {
    type: 'transformer_load', label: 'Transformer Load', category: 'deploy',
    description: 'Load a saved transformer and apply it to a dataset',
    inputs: [{ name: 'dataset', type: 'dataset' }],
    outputs: [{ name: 'dataset', type: 'dataset' }],
    config: [
      { id: 'path', label: 'Load Path (inside ~/.athena/transformers/)', type: 'text', default: 'transformer.pkl' },
      { id: 'cols', label: 'Columns to Transform (comma-sep, blank = auto)', type: 'text', default: '' },
    ],
  },

  // ── MONITORING ────────────────────────────────────────────────────────────
  drift_detect: {
    type: 'drift_detect', label: 'Drift Detection', category: 'monitor',
    description: 'Detect feature and concept drift',
    inputs: [{ name: 'dataset', type: 'dataset' }, { name: 'reference', type: 'dataset' }],
    outputs: [{ name: 'report', type: 'report' }],
    config: [
      { id: 'method', label: 'Method', type: 'select', options: ['PSI', 'KS Test', 'Chi-squared'], default: 'KS Test' },
      { id: 'threshold', label: 'Threshold', type: 'number', default: 0.05 },
    ],
  },
  perf_tracker: {
    type: 'perf_tracker', label: 'Performance Tracker', category: 'monitor',
    description: 'Track model performance over time',
    inputs: [{ name: 'model', type: 'model' }, { name: 'dataset', type: 'dataset' }],
    outputs: [{ name: 'report', type: 'report' }],
    config: [
      { id: 'metric', label: 'Metric', type: 'select', options: ['accuracy', 'f1', 'rmse'], default: 'accuracy' },
      { id: 'window', label: 'Window (days)', type: 'number', default: 7 },
    ],
  },
}

export interface NodeGroup {
  id: NodeCategory
  label: string
  color: string
  icon: string
  nodes: NodeSpec[]
}

export const NODE_GROUPS: NodeGroup[] = Object.entries(CATEGORY_META).map(([catId, catMeta]) => ({
  id: catId as NodeCategory,
  ...catMeta,
  nodes: Object.values(NODE_REGISTRY).filter(n => n.category === catId),
}))
