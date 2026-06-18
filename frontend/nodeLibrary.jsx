// Node type definitions and Left Sidebar component

const NODE_REGISTRY = {
  // DATA INPUT
  csv_loader:    { label: 'CSV Loader',           cat: 'data',     inputs: [],                    outputs: ['dataset'],             desc: 'Load data from a CSV file', icon: '⬡', config: [{id:'path',label:'File Path',type:'text',default:'data.csv'},{id:'sep',label:'Separator',type:'select',options:[',',';','\\t','|'],default:','},{id:'header',label:'Header Row',type:'toggle',default:true},{id:'encoding',label:'Encoding',type:'select',options:['utf-8','latin-1','utf-16'],default:'utf-8'}] },
  excel_loader:  { label: 'Excel Loader',         cat: 'data',     inputs: [],                    outputs: ['dataset'],             desc: 'Load data from an Excel file', icon: '⬡', config: [{id:'path',label:'File Path',type:'text',default:'data.xlsx'},{id:'sheet',label:'Sheet Name',type:'text',default:'Sheet1'},{id:'header',label:'Header Row',type:'toggle',default:true}] },
  json_loader:   { label: 'JSON Loader',           cat: 'data',     inputs: [],                    outputs: ['dataset'],             desc: 'Load structured JSON data', icon: '⬡', config: [{id:'path',label:'File Path',type:'text',default:'data.json'},{id:'orient',label:'Orientation',type:'select',options:['records','index','columns','values'],default:'records'}] },
  db_connector:  { label: 'DB Connector',          cat: 'data',     inputs: [],                    outputs: ['dataset'],             desc: 'Connect to MySQL / PostgreSQL', icon: '⬡', config: [{id:'host',label:'Host',type:'text',default:'localhost'},{id:'port',label:'Port',type:'number',default:5432},{id:'db',label:'Database',type:'text',default:'mydb'},{id:'query',label:'SQL Query',type:'textarea',default:'SELECT * FROM table LIMIT 1000'}] },
  api_fetch:     { label: 'API Fetch',             cat: 'data',     inputs: [],                    outputs: ['dataset'],             desc: 'Fetch data from a REST API endpoint', icon: '⬡', config: [{id:'url',label:'URL',type:'text',default:'https://api.example.com/data'},{id:'method',label:'Method',type:'select',options:['GET','POST'],default:'GET'},{id:'auth',label:'Auth Token',type:'text',default:''}] },
  synth_data:    { label: 'Synthetic Data',        cat: 'data',     inputs: [],                    outputs: ['dataset'],             desc: 'Generate synthetic training data', icon: '⬡', config: [{id:'rows',label:'Rows',type:'number',default:1000},{id:'features',label:'Features',type:'number',default:10},{id:'task',label:'Task Type',type:'select',options:['classification','regression','clustering'],default:'classification'}] },
  data_merge:    { label: 'Data Merge / Join',     cat: 'data',     inputs: ['left','right'],       outputs: ['dataset'],            desc: 'Merge two datasets on a key column', icon: '⬡', config: [{id:'on',label:'Join Key',type:'text',default:'id'},{id:'how',label:'Join Type',type:'select',options:['inner','left','right','outer'],default:'inner'}] },
  data_sample:   { label: 'Data Sampling',         cat: 'data',     inputs: ['dataset'],            outputs: ['dataset'],            desc: 'Sample rows from dataset', icon: '⬡', config: [{id:'n',label:'Sample Size',type:'number',default:500},{id:'frac',label:'Fraction',type:'number',default:0.1},{id:'random_state',label:'Random Seed',type:'number',default:42}] },
  // DATA QUALITY
  imputer:       { label: 'Missing Value Imputer', cat: 'quality',  inputs: ['dataset'],            outputs: ['dataset'],            desc: 'Fill missing values using various strategies', icon: '⬡', config: [{id:'strategy',label:'Strategy',type:'select',options:['mean','median','mode','constant','knn'],default:'mean'},{id:'fill_value',label:'Fill Value',type:'text',default:'0'},{id:'cols',label:'Columns (comma-sep)',type:'text',default:''}] },
  dup_remover:   { label: 'Duplicate Remover',     cat: 'quality',  inputs: ['dataset'],            outputs: ['dataset'],            desc: 'Remove duplicate rows', icon: '⬡', config: [{id:'subset',label:'Subset Columns',type:'text',default:''},{id:'keep',label:'Keep',type:'select',options:['first','last','none'],default:'first'}] },
  outlier:       { label: 'Outlier Detector',      cat: 'quality',  inputs: ['dataset'],            outputs: ['dataset','outliers'], desc: 'Detect and handle outliers', icon: '⬡', config: [{id:'method',label:'Method',type:'select',options:['IQR','Z-Score','Isolation Forest'],default:'IQR'},{id:'action',label:'Action',type:'select',options:['remove','clip','flag'],default:'remove'},{id:'threshold',label:'Threshold',type:'number',default:3}] },
  type_conv:     { label: 'Type Converter',        cat: 'quality',  inputs: ['dataset'],            outputs: ['dataset'],            desc: 'Convert column data types', icon: '⬡', config: [{id:'rules',label:'Conversion Rules',type:'textarea',default:'col1: float\ncol2: int'}] },
  validator:     { label: 'Data Validator',        cat: 'quality',  inputs: ['dataset'],            outputs: ['dataset','report'],   desc: 'Enforce schema and constraints', icon: '⬡', config: [{id:'schema',label:'Schema (JSON)',type:'textarea',default:'{"col1": "float", "col2": "str"}'},{id:'strict',label:'Strict Mode',type:'toggle',default:false}] },
  // FEATURE ENGINEERING
  col_selector:  { label: 'Column Selector',       cat: 'feature',  inputs: ['dataset'],            outputs: ['dataset'],            desc: 'Select or drop columns', icon: '⬡', config: [{id:'mode',label:'Mode',type:'select',options:['include','exclude'],default:'include'},{id:'cols',label:'Columns',type:'text',default:'col1, col2, col3'}] },
  ohe:           { label: 'One-Hot Encoder',        cat: 'feature',  inputs: ['dataset'],            outputs: ['dataset'],            desc: 'Encode categorical columns as binary', icon: '⬡', config: [{id:'cols',label:'Columns',type:'text',default:''},{id:'drop',label:'Drop First',type:'toggle',default:false},{id:'sparse',label:'Sparse Output',type:'toggle',default:false}] },
  label_enc:     { label: 'Label Encoder',          cat: 'feature',  inputs: ['dataset'],            outputs: ['dataset'],            desc: 'Encode labels as integers', icon: '⬡', config: [{id:'cols',label:'Columns',type:'text',default:'target'}] },
  scaler:        { label: 'Scaler',                 cat: 'feature',  inputs: ['dataset'],            outputs: ['dataset'],            desc: 'Normalize or standardize features', icon: '⬡', config: [{id:'method',label:'Method',type:'select',options:['StandardScaler','MinMaxScaler','RobustScaler','MaxAbsScaler'],default:'StandardScaler'},{id:'cols',label:'Columns',type:'text',default:''}] },
  feat_gen:      { label: 'Feature Generator',      cat: 'feature',  inputs: ['dataset'],            outputs: ['dataset'],            desc: 'Create polynomial or interaction features', icon: '⬡', config: [{id:'degree',label:'Degree',type:'number',default:2},{id:'interaction',label:'Interaction Only',type:'toggle',default:false}] },
  tfidf:         { label: 'Text Vectorizer',        cat: 'feature',  inputs: ['dataset'],            outputs: ['dataset'],            desc: 'TF-IDF or CountVectorizer for text', icon: '⬡', config: [{id:'col',label:'Text Column',type:'text',default:'text'},{id:'method',label:'Method',type:'select',options:['TF-IDF','CountVectorizer'],default:'TF-IDF'},{id:'max_features',label:'Max Features',type:'number',default:1000}] },
  embedding:     { label: 'Embedding Generator',    cat: 'feature',  inputs: ['dataset'],            outputs: ['dataset'],            desc: 'Generate embeddings for text or categories', icon: '⬡', config: [{id:'col',label:'Column',type:'text',default:'text'},{id:'dim',label:'Dimensions',type:'number',default:128}] },
  date_feat:     { label: 'Date Feature Extractor', cat: 'feature',  inputs: ['dataset'],            outputs: ['dataset'],            desc: 'Extract year, month, day, weekday, etc.', icon: '⬡', config: [{id:'col',label:'Date Column',type:'text',default:'date'},{id:'features',label:'Extract',type:'text',default:'year,month,day,weekday'}] },
  feat_imp_sel:  { label: 'Feature Importance Sel', cat: 'feature',  inputs: ['dataset'],            outputs: ['dataset'],            desc: 'Select top features by importance score', icon: '⬡', config: [{id:'k',label:'Top K Features',type:'number',default:20},{id:'method',label:'Method',type:'select',options:['chi2','f_classif','mutual_info'],default:'f_classif'}] },
  pca:           { label: 'PCA',                    cat: 'feature',  inputs: ['dataset'],            outputs: ['dataset'],            desc: 'Principal Component Analysis', icon: '⬡', config: [{id:'n_components',label:'Components',type:'number',default:10},{id:'whiten',label:'Whiten',type:'toggle',default:false}] },
  // DATA BALANCING
  smote:         { label: 'SMOTE',                  cat: 'balance',  inputs: ['dataset'],            outputs: ['dataset'],            desc: 'Oversample minority class synthetically', icon: '⬡', config: [{id:'k_neighbors',label:'K Neighbors',type:'number',default:5},{id:'random_state',label:'Random Seed',type:'number',default:42}] },
  undersample:   { label: 'Undersampling',           cat: 'balance',  inputs: ['dataset'],            outputs: ['dataset'],            desc: 'Reduce majority class samples', icon: '⬡', config: [{id:'strategy',label:'Strategy',type:'select',options:['random','tomek','enn'],default:'random'},{id:'ratio',label:'Ratio',type:'number',default:1.0}] },
  oversample:    { label: 'Oversampling',            cat: 'balance',  inputs: ['dataset'],            outputs: ['dataset'],            desc: 'Duplicate minority class samples', icon: '⬡', config: [{id:'strategy',label:'Strategy',type:'select',options:['random','adasyn'],default:'random'}] },
  class_weight:  { label: 'Class Weight Adjuster',  cat: 'balance',  inputs: ['dataset'],            outputs: ['dataset'],            desc: 'Balance via class weights', icon: '⬡', config: [{id:'mode',label:'Mode',type:'select',options:['balanced','auto','custom'],default:'balanced'}] },
  // DATA SPLIT
  train_test:    { label: 'Train / Test Split',     cat: 'split',    inputs: ['dataset'],            outputs: ['train','test'],       desc: 'Split into training and test sets', icon: '⬡', config: [{id:'test_size',label:'Test Size',type:'number',default:0.2},{id:'random_state',label:'Random Seed',type:'number',default:42},{id:'stratify',label:'Stratify',type:'toggle',default:false}] },
  train_val_test:{ label: 'Train/Val/Test Split',   cat: 'split',    inputs: ['dataset'],            outputs: ['train','val','test'],  desc: 'Three-way dataset split', icon: '⬡', config: [{id:'val_size',label:'Val Size',type:'number',default:0.1},{id:'test_size',label:'Test Size',type:'number',default:0.2},{id:'random_state',label:'Random Seed',type:'number',default:42}] },
  cv_split:      { label: 'Cross-Validation Split', cat: 'split',    inputs: ['dataset'],            outputs: ['folds'],              desc: 'K-Fold or Stratified K-Fold', icon: '⬡', config: [{id:'k',label:'K Folds',type:'number',default:5},{id:'method',label:'Method',type:'select',options:['KFold','StratifiedKFold','GroupKFold'],default:'StratifiedKFold'},{id:'shuffle',label:'Shuffle',type:'toggle',default:true}] },
  // MODEL NODES
  lin_reg:       { label: 'Linear Regression',      cat: 'model',    inputs: ['train'],              outputs: ['model'],              desc: 'Ordinary least squares regression', icon: '⬡', config: [{id:'fit_intercept',label:'Fit Intercept',type:'toggle',default:true},{id:'normalize',label:'Normalize',type:'toggle',default:false}] },
  log_reg:       { label: 'Logistic Regression',    cat: 'model',    inputs: ['train'],              outputs: ['model'],              desc: 'Binary or multiclass classification', icon: '⬡', config: [{id:'C',label:'C (Regularization)',type:'number',default:1.0},{id:'solver',label:'Solver',type:'select',options:['lbfgs','saga','liblinear'],default:'lbfgs'},{id:'max_iter',label:'Max Iterations',type:'number',default:100}] },
  dtree:         { label: 'Decision Tree',           cat: 'model',    inputs: ['train'],              outputs: ['model'],              desc: 'Decision tree classifier/regressor', icon: '⬡', config: [{id:'max_depth',label:'Max Depth',type:'number',default:5},{id:'min_samples_split',label:'Min Samples Split',type:'number',default:2},{id:'criterion',label:'Criterion',type:'select',options:['gini','entropy'],default:'gini'}] },
  rf:            { label: 'Random Forest',           cat: 'model',    inputs: ['train'],              outputs: ['model'],              desc: 'Ensemble of decision trees', icon: '⬡', config: [{id:'n_estimators',label:'Estimators',type:'number',default:100},{id:'max_depth',label:'Max Depth',type:'number',default:10},{id:'max_features',label:'Max Features',type:'select',options:['sqrt','log2','auto'],default:'sqrt'},{id:'random_state',label:'Random Seed',type:'number',default:42}] },
  xgb:           { label: 'XGBoost',                cat: 'model',    inputs: ['train'],              outputs: ['model'],              desc: 'Gradient boosting — high performance', icon: '⬡', config: [{id:'n_estimators',label:'Estimators',type:'number',default:100},{id:'learning_rate',label:'Learning Rate',type:'number',default:0.1},{id:'max_depth',label:'Max Depth',type:'number',default:6},{id:'subsample',label:'Subsample',type:'number',default:0.8}] },
  svm:           { label: 'Support Vector Machine',  cat: 'model',    inputs: ['train'],              outputs: ['model'],              desc: 'SVM for classification or regression', icon: '⬡', config: [{id:'C',label:'C',type:'number',default:1.0},{id:'kernel',label:'Kernel',type:'select',options:['rbf','linear','poly','sigmoid'],default:'rbf'},{id:'gamma',label:'Gamma',type:'select',options:['scale','auto'],default:'scale'}] },
  knn:           { label: 'KNN',                     cat: 'model',    inputs: ['train'],              outputs: ['model'],              desc: 'K-Nearest Neighbors', icon: '⬡', config: [{id:'n_neighbors',label:'Neighbors',type:'number',default:5},{id:'metric',label:'Metric',type:'select',options:['euclidean','manhattan','cosine'],default:'euclidean'},{id:'weights',label:'Weights',type:'select',options:['uniform','distance'],default:'uniform'}] },
  nb:            { label: 'Naive Bayes',             cat: 'model',    inputs: ['train'],              outputs: ['model'],              desc: 'Probabilistic classifier', icon: '⬡', config: [{id:'variant',label:'Variant',type:'select',options:['GaussianNB','MultinomialNB','BernoulliNB'],default:'GaussianNB'},{id:'var_smoothing',label:'Var Smoothing',type:'number',default:1e-9}] },
  mlp:           { label: 'Neural Network (MLP)',    cat: 'model',    inputs: ['train'],              outputs: ['model'],              desc: 'Multilayer perceptron', icon: '⬡', config: [{id:'layers',label:'Hidden Layers',type:'text',default:'128, 64, 32'},{id:'activation',label:'Activation',type:'select',options:['relu','tanh','sigmoid'],default:'relu'},{id:'lr',label:'Learning Rate',type:'number',default:0.001},{id:'epochs',label:'Epochs',type:'number',default:100},{id:'batch_size',label:'Batch Size',type:'number',default:32}] },
  // ADVANCED
  automl:        { label: 'AutoML Search',           cat: 'advanced', inputs: ['train'],              outputs: ['model','report'],     desc: 'Auto-select best model and hyperparams', icon: '⬡', config: [{id:'time_budget',label:'Time Budget (s)',type:'number',default:60},{id:'metric',label:'Optimize',type:'select',options:['accuracy','f1','roc_auc','rmse','r2'],default:'accuracy'},{id:'n_trials',label:'Trials',type:'number',default:50}] },
  hp_tuner:      { label: 'Hyperparameter Tuner',   cat: 'advanced', inputs: ['train'],              outputs: ['model'],              desc: 'Grid, Random, or Bayesian search', icon: '⬡', config: [{id:'method',label:'Method',type:'select',options:['Grid','Random','Bayesian'],default:'Bayesian'},{id:'n_iter',label:'Iterations',type:'number',default:25},{id:'cv',label:'CV Folds',type:'number',default:3}] },
  pipeline_wrap: { label: 'Pipeline Wrapper',        cat: 'advanced', inputs: ['dataset','model'],    outputs: ['pipeline'],           desc: 'Wrap preprocessing + model into a pipeline', icon: '⬡', config: [{id:'memory',label:'Cache Pipeline',type:'toggle',default:false}] },
  custom_code:   { label: 'Custom Code Node',        cat: 'advanced', inputs: ['dataset'],            outputs: ['dataset'],            desc: 'Execute custom Python snippet', icon: '⬡', config: [{id:'code',label:'Python Code',type:'textarea',default:'# df is your DataFrame\ndf["new_col"] = df["col1"] * 2\nreturn df'}] },
  // ENSEMBLE
  voting:        { label: 'Voting Classifier',       cat: 'ensemble', inputs: ['model','model'],      outputs: ['model'],              desc: 'Combine multiple models by voting', icon: '⬡', config: [{id:'voting',label:'Voting',type:'select',options:['hard','soft'],default:'soft'},{id:'weights',label:'Weights',type:'text',default:''}] },
  stacking:      { label: 'Stacking Ensemble',       cat: 'ensemble', inputs: ['model','model'],      outputs: ['model'],              desc: 'Stack models with a meta-learner', icon: '⬡', config: [{id:'meta',label:'Meta Learner',type:'select',options:['LogisticRegression','LinearRegression'],default:'LogisticRegression'},{id:'cv',label:'CV Folds',type:'number',default:5}] },
  blending:      { label: 'Blending Node',           cat: 'ensemble', inputs: ['model','model'],      outputs: ['model'],              desc: 'Blend predictions from multiple models', icon: '⬡', config: [{id:'method',label:'Method',type:'select',options:['mean','weighted_mean','rank_avg'],default:'mean'}] },
  // EVAL
  metrics:       { label: 'Metrics Node',            cat: 'eval',     inputs: ['model','test'],       outputs: ['report'],             desc: 'Compute classification or regression metrics', icon: '⬡', config: [{id:'task',label:'Task',type:'select',options:['classification','regression'],default:'classification'},{id:'average',label:'Average',type:'select',options:['micro','macro','weighted'],default:'weighted'}] },
  conf_matrix:   { label: 'Confusion Matrix',        cat: 'eval',     inputs: ['model','test'],       outputs: ['plot'],               desc: 'Visualize prediction confusion matrix', icon: '⬡', config: [{id:'normalize',label:'Normalize',type:'select',options:['true','pred','all','none'],default:'none'},{id:'cmap',label:'Colormap',type:'text',default:'Blues'}] },
  roc_curve:     { label: 'ROC Curve',               cat: 'eval',     inputs: ['model','test'],       outputs: ['plot'],               desc: 'Plot ROC-AUC curve', icon: '⬡', config: [{id:'multi_class',label:'Multi-class Strategy',type:'select',options:['ovr','ovo'],default:'ovr'}] },
  feat_imp_viz:  { label: 'Feature Importance Viz',  cat: 'eval',     inputs: ['model'],              outputs: ['plot'],               desc: 'Visualize feature importances', icon: '⬡', config: [{id:'top_n',label:'Top N Features',type:'number',default:20}] },
  residual:      { label: 'Residual Analysis',       cat: 'eval',     inputs: ['model','test'],       outputs: ['plot'],               desc: 'Analyze regression residuals', icon: '⬡', config: [] },
  // INTERPRETABILITY
  shap:          { label: 'SHAP Explainer',          cat: 'interp',   inputs: ['model','dataset'],    outputs: ['report'],             desc: 'SHAP-based model explanations', icon: '⬡', config: [{id:'plot',label:'Plot Type',type:'select',options:['summary','bar','waterfall','beeswarm'],default:'summary'},{id:'n_samples',label:'Samples',type:'number',default:100}] },
  lime:          { label: 'LIME Explainer',          cat: 'interp',   inputs: ['model','dataset'],    outputs: ['report'],             desc: 'Local interpretable explanations', icon: '⬡', config: [{id:'n_features',label:'Top Features',type:'number',default:10},{id:'mode',label:'Mode',type:'select',options:['classification','regression'],default:'classification'}] },
  debugger:      { label: 'Model Debugger',          cat: 'interp',   inputs: ['model','test'],       outputs: ['report'],             desc: 'Diagnose model issues and errors', icon: '⬡', config: [] },
  // DEPLOYMENT
  predict:       { label: 'Prediction Node',         cat: 'deploy',   inputs: ['model','dataset'],    outputs: ['predictions'],        desc: 'Batch prediction on new data', icon: '⬡', config: [{id:'output_col',label:'Output Column',type:'text',default:'y_pred'},{id:'proba',label:'Return Probabilities',type:'toggle',default:false}] },
  api_gen:       { label: 'API Generator',           cat: 'deploy',   inputs: ['model'],              outputs: ['endpoint'],           desc: 'Expose model as REST API endpoint', icon: '⬡', config: [{id:'host',label:'Host',type:'text',default:'0.0.0.0'},{id:'port',label:'Port',type:'number',default:8000},{id:'framework',label:'Framework',type:'select',options:['FastAPI','Flask'],default:'FastAPI'}] },
  csv_export:    { label: 'CSV Export',              cat: 'deploy',   inputs: ['dataset'],            outputs: [],                     desc: 'Save dataset to CSV file', icon: '⬡', config: [{id:'path',label:'Output Path',type:'text',default:'output.csv'},{id:'index',label:'Include Index',type:'toggle',default:false}] },
  model_saver:   { label: 'Model Saver',             cat: 'deploy',   inputs: ['model'],              outputs: [],                     desc: 'Serialize model with pickle/joblib', icon: '⬡', config: [{id:'path',label:'Save Path',type:'text',default:'model.pkl'},{id:'format',label:'Format',type:'select',options:['joblib','pickle'],default:'joblib'}] },
  report_gen:    { label: 'Report Generator',        cat: 'deploy',   inputs: ['report'],             outputs: [],                     desc: 'Generate PDF/HTML summary report', icon: '⬡', config: [{id:'format',label:'Format',type:'select',options:['HTML','PDF','Jupyter'],default:'HTML'},{id:'path',label:'Output Path',type:'text',default:'report.html'}] },
  // MONITORING
  drift_detect:  { label: 'Drift Detection',         cat: 'monitor',  inputs: ['dataset','dataset'],  outputs: ['report'],             desc: 'Detect feature and concept drift', icon: '⬡', config: [{id:'method',label:'Method',type:'select',options:['PSI','KS Test','Chi-squared'],default:'KS Test'},{id:'threshold',label:'Threshold',type:'number',default:0.05}] },
  perf_tracker:  { label: 'Performance Tracker',     cat: 'monitor',  inputs: ['model','dataset'],    outputs: ['report'],             desc: 'Track model performance over time', icon: '⬡', config: [{id:'metric',label:'Metric',type:'select',options:['accuracy','f1','rmse'],default:'accuracy'},{id:'window',label:'Window (days)',type:'number',default:7}] },
};

const CATEGORY_META = {
  data:     { label: 'Data Input',         color: 'var(--cat-data)',     icon: '⊞' },
  quality:  { label: 'Data Quality',       color: 'var(--cat-quality)',  icon: '✦' },
  feature:  { label: 'Feature Eng.',       color: 'var(--cat-feature)',  icon: '◈' },
  balance:  { label: 'Data Balancing',     color: 'var(--cat-balance)',  icon: '⊜' },
  split:    { label: 'Data Split',         color: 'var(--cat-split)',    icon: '⋈' },
  model:    { label: 'Models',             color: 'var(--cat-model)',    icon: '◉' },
  advanced: { label: 'Advanced ML',        color: 'var(--cat-advanced)', icon: '◎' },
  ensemble: { label: 'Ensemble',           color: 'var(--cat-ensemble)', icon: '⊕' },
  eval:     { label: 'Evaluation',         color: 'var(--cat-eval)',     icon: '◇' },
  interp:   { label: 'Interpretability',   color: 'var(--cat-interp)',   icon: '◑' },
  deploy:   { label: 'Deployment',         color: 'var(--cat-deploy)',   icon: '⊳' },
  monitor:  { label: 'Monitoring',         color: 'var(--cat-monitor)',  icon: '◐' },
};

// Build grouped structure
const NODE_GROUPS = Object.entries(CATEGORY_META).map(([catId, catMeta]) => ({
  id: catId,
  ...catMeta,
  nodes: Object.entries(NODE_REGISTRY)
    .filter(([, nd]) => nd.cat === catId)
    .map(([type, nd]) => ({ type, ...nd }))
}));

// ─── Left Sidebar ───────────────────────────────────────────────────────────
const { useState: useStateLib, useRef: useRefLib, useMemo: useMemoLib } = React;

function LeftSidebar({ onDragStart }) {
  const [search, setSearch] = useStateLib('');
  const [collapsed, setCollapsed] = useStateLib({});

  const filtered = useMemoLib(() => {
    const q = search.toLowerCase();
    return NODE_GROUPS.map(g => ({
      ...g,
      nodes: g.nodes.filter(n => n.label.toLowerCase().includes(q) || n.desc.toLowerCase().includes(q))
    })).filter(g => g.nodes.length > 0);
  }, [search]);

  const toggle = id => setCollapsed(p => ({ ...p, [id]: !p[id] }));

  const sidebarStyle = {
    width: 240,
    minWidth: 240,
    background: 'var(--panel)',
    borderRight: '1px solid var(--border)',
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    overflow: 'hidden',
  };
  const headerStyle = {
    padding: '14px 14px 10px',
    borderBottom: '1px solid var(--border)',
    flexShrink: 0,
  };
  const titleStyle = { fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 8 };
  const searchStyle = {
    width: '100%', background: 'var(--card)', border: '1px solid var(--border)',
    borderRadius: 6, padding: '6px 10px', color: 'var(--text)', fontSize: 12,
    outline: 'none', fontFamily: 'var(--font)',
  };
  const listStyle = { flex: 1, overflowY: 'auto', padding: '8px 0' };

  return (
    <div style={sidebarStyle}>
      <div style={headerStyle}>
        <div style={titleStyle}>Node Library</div>
        <input
          style={searchStyle}
          placeholder="Search nodes…"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
      </div>
      <div style={listStyle}>
        {filtered.map(group => (
          <NodeGroup key={group.id} group={group} collapsed={collapsed[group.id]} onToggle={() => toggle(group.id)} onDragStart={onDragStart} />
        ))}
      </div>
    </div>
  );
}

function NodeGroup({ group, collapsed, onToggle, onDragStart }) {
  const headerStyle = {
    display: 'flex', alignItems: 'center', gap: 6,
    padding: '6px 14px', cursor: 'pointer', userSelect: 'none',
    fontSize: 11, fontWeight: 600, letterSpacing: '0.04em',
    color: 'var(--text-dim)',
  };
  const dotStyle = { width: 7, height: 7, borderRadius: '50%', background: group.color, flexShrink: 0 };
  const chevStyle = { marginLeft: 'auto', fontSize: 9, color: 'var(--text-muted)', transition: 'transform 0.15s', transform: collapsed ? 'rotate(-90deg)' : 'rotate(0deg)' };

  return (
    <div>
      <div style={headerStyle} onClick={onToggle}>
        <div style={dotStyle}></div>
        <span style={{ color: group.color }}>{group.icon}</span>
        <span>{group.label}</span>
        <span style={chevStyle}>▾</span>
      </div>
      {!collapsed && (
        <div>
          {group.nodes.map(node => (
            <NodeLibItem key={node.type} node={node} color={group.color} onDragStart={onDragStart} />
          ))}
        </div>
      )}
    </div>
  );
}

function NodeLibItem({ node, color, onDragStart }) {
  const [hov, setHov] = useStateLib(false);
  const style = {
    display: 'flex', alignItems: 'center', gap: 8,
    padding: '5px 14px 5px 26px',
    cursor: 'grab',
    background: hov ? 'var(--card)' : 'transparent',
    transition: 'background 0.1s',
    userSelect: 'none',
  };
  const dotStyle = { width: 5, height: 5, borderRadius: '50%', background: color, flexShrink: 0 };
  const labelStyle = { fontSize: 12, color: hov ? 'var(--text)' : 'var(--text-dim)', transition: 'color 0.1s', lineHeight: 1.3 };

  return (
    <div
      style={style}
      draggable
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      onDragStart={e => onDragStart(e, node.type)}
      title={node.desc}
    >
      <div style={dotStyle}></div>
      <span style={labelStyle}>{node.label}</span>
    </div>
  );
}

Object.assign(window, { NODE_REGISTRY, NODE_GROUPS, CATEGORY_META, LeftSidebar });
