from pydantic import BaseModel
from typing import Any, Literal
import pandas as pd
from sklearn.linear_model import LinearRegression, LogisticRegression, Ridge, Lasso
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor, GradientBoostingRegressor
from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor
from sklearn.svm import SVC, SVR
from sklearn.neighbors import KNeighborsClassifier, KNeighborsRegressor
from sklearn.naive_bayes import GaussianNB, MultinomialNB, BernoulliNB
from sklearn.neural_network import MLPClassifier, MLPRegressor

from athena.nodes.export import EXPORT
from athena.sdk import Port, node, ui
from athena.core.handler import ExecutionContext, HandlerResult
from athena.schemas.artifacts import ModelPreview


def _fit_model(X_train: pd.DataFrame, y_train: pd.Series, model_obj: object, ctx: ExecutionContext) -> tuple[object, ModelPreview]:
    ctx.logger.info("Fitting", model=type(model_obj).__name__, samples=len(X_train), features=len(X_train.columns))
    model_obj.fit(X_train, y_train)  # type: ignore[union-attr]
    ctx.logger.info("Fit complete")
    return model_obj, ModelPreview(summary=repr(model_obj))


def _tune_model(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    model_obj: object,
    hpconfig: dict[str, Any],
    ctx: ExecutionContext,
) -> tuple[object, ModelPreview]:
    from sklearn.model_selection import GridSearchCV, RandomizedSearchCV

    method = str(hpconfig.get("method", "Random"))
    scoring = str(hpconfig.get("scoring", "accuracy"))
    n_iter = int(hpconfig.get("n_iter", 25))
    cv = int(hpconfig.get("cv", 5))
    n_jobs = int(hpconfig.get("n_jobs", -1))
    param_grid: dict[str, list] = hpconfig.get("param_grid", {})  # type: ignore[assignment]

    if not param_grid:
        ctx.logger.warning("HP tune config has empty param_grid — fitting without search")
        return _fit_model(X_train, y_train, model_obj, ctx)

    ctx.logger.info("Starting HP search", method=method, scoring=scoring, cv=cv, params=list(param_grid.keys()))

    if method == "Optuna":
        return _optuna_search(X_train, y_train, model_obj, param_grid, scoring, n_iter, cv, n_jobs, ctx)
    if method == "Grid":
        search: Any = GridSearchCV(model_obj, param_grid, cv=cv, n_jobs=n_jobs, scoring=scoring)
    elif method == "Bayesian":
        try:
            from skopt import BayesSearchCV  # type: ignore[import-untyped]
            search = BayesSearchCV(
                model_obj, param_grid, n_iter=n_iter, cv=cv,
                n_jobs=n_jobs, scoring=scoring, random_state=42,
            )
        except ImportError:
            ctx.logger.warning("scikit-optimize not installed, falling back to RandomizedSearchCV")
            search = RandomizedSearchCV(
                model_obj, param_grid, n_iter=min(n_iter, 50), cv=cv,
                n_jobs=n_jobs, scoring=scoring, random_state=42,
            )
    else:
        search = RandomizedSearchCV(
            model_obj, param_grid, n_iter=min(n_iter, 50), cv=cv,
            n_jobs=n_jobs, scoring=scoring, random_state=42,
        )

    search.fit(X_train, y_train)
    best: object = search.best_estimator_
    ctx.logger.info("HP search done", best_score=search.best_score_, params=search.best_params_)
    return best, ModelPreview(
        summary=f"Best CV score: {search.best_score_:.4f}\nBest params: {search.best_params_}\n\n{repr(best)}"
    )


OPTUNA_HINT = "Optuna isn't installed. Run: pip install 'athena-backend[optuna]' (in backend/: uv sync --extra optuna)"


def _optuna_space(values: list[Any]) -> tuple[str, Any]:
    """More than three numbers = a range to search continuously; otherwise a set of choices."""
    numeric = all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values)
    if numeric and len(values) > 3:
        lo, hi = min(values), max(values)
        if all(isinstance(v, int) for v in values):
            return "int", (int(lo), int(hi))
        return "float", (float(lo), float(hi), lo > 0 and hi / lo >= 100)  # log scale for wide positive ranges
    return "categorical", list(values)


def _optuna_search(
    X_train: pd.DataFrame, y_train: pd.Series, model_obj: object, param_grid: dict[str, list[Any]],
    scoring: str, n_trials: int, cv: int, n_jobs: int, ctx: ExecutionContext,
) -> tuple[object, ModelPreview]:
    import importlib.util
    if importlib.util.find_spec("optuna") is None:
        raise RuntimeError(OPTUNA_HINT)
    import optuna
    from sklearn.base import clone
    from sklearn.model_selection import cross_val_score

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    space = {k: _optuna_space(v) for k, v in param_grid.items()}
    ctx.logger.info("Optuna search space", **{k: f"{kind} {spec}" for k, (kind, spec) in space.items()})

    def objective(trial: Any) -> float:
        params: dict[str, Any] = {}
        for name, (kind, spec) in space.items():
            if kind == "int":
                params[name] = trial.suggest_int(name, *spec)
            elif kind == "float":
                params[name] = trial.suggest_float(name, spec[0], spec[1], log=spec[2])
            else:
                params[name] = trial.suggest_categorical(name, spec)
        model = clone(model_obj).set_params(**params)  # type: ignore[attr-defined]
        return float(cross_val_score(model, X_train, y_train, cv=cv, scoring=scoring, n_jobs=n_jobs).mean())

    def report(study: Any, trial: Any) -> None:
        if trial.value is not None:
            ctx.logger.info(f"Trial {trial.number + 1}/{n_trials}: {scoring}={trial.value:.4f} (best {study.best_value:.4f})")
        if ctx.cancelled():
            study.stop()

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=42))
    study.optimize(objective, n_trials=n_trials, callbacks=[report])
    best = clone(model_obj).set_params(**study.best_params)  # type: ignore[attr-defined]
    best.fit(X_train, y_train)  # type: ignore[attr-defined]
    ctx.logger.info("Optuna search done", best_score=round(study.best_value, 4), params=study.best_params)
    summary = (f"Optuna ({len(study.trials)} trials) best CV {scoring}: {study.best_value:.4f}\n"
               f"Best params: {study.best_params}\n\n{best!r}")
    return best, ModelPreview(summary=summary)


def _fit_or_tune(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    model_obj: object,
    ctx: ExecutionContext,
) -> tuple[object, ModelPreview]:
    hpconfig: dict[str, Any] | None = ctx.inputs[4] if len(ctx.inputs) > 4 and ctx.inputs[4] is not None else None
    if hpconfig:
        return _tune_model(X_train, y_train, model_obj, hpconfig, ctx)
    return _fit_model(X_train, y_train, model_obj, ctx)




@node(
    "lin_reg", label="Linear Regression", category="model",
    description="Ordinary least squares regression",
    inputs=[Port("X_train", "X_train"), Port("y_train", "y_train"), Port("X_val", "X_val", optional=True), Port("y_val", "y_val", optional=True), Port("hp_config", "hpconfig", optional=True)],
    outputs=[Port("model", "model")],
    fields={
        "fit_intercept": ui("Fit Intercept"),
    },
    code=EXPORT["lin_reg"],
)
class LinRegHandler:
    class Config(BaseModel):
        fit_intercept: bool = True

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        X_train: pd.DataFrame = ctx.inputs[0]
        y_train: pd.Series = ctx.inputs[1]
        model, preview = _fit_or_tune(X_train, y_train, LinearRegression(fit_intercept=cfg.fit_intercept), ctx)
        return HandlerResult(outputs=[model], preview=preview)




@node(
    "log_reg", label="Logistic Regression", category="model",
    description="Binary or multiclass classification",
    inputs=[Port("X_train", "X_train"), Port("y_train", "y_train"), Port("X_val", "X_val", optional=True), Port("y_val", "y_val", optional=True), Port("hp_config", "hpconfig", optional=True)],
    outputs=[Port("model", "model")],
    fields={
        "C": ui("C (Regularization)"),
        "solver": ui(),
        "max_iter": ui("Max Iterations"),
    },
    code=EXPORT["log_reg"],
)
class LogRegHandler:
    class Config(BaseModel):
        C: float = 1.0
        solver: Literal["lbfgs", "saga", "liblinear"] = "lbfgs"
        max_iter: int = 100

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        X_train: pd.DataFrame = ctx.inputs[0]
        y_train: pd.Series = ctx.inputs[1]
        model, preview = _fit_or_tune(
            X_train, y_train,
            LogisticRegression(C=cfg.C, solver=cfg.solver, max_iter=cfg.max_iter),
            ctx,
        )
        return HandlerResult(outputs=[model], preview=preview)




@node(
    "rf", label="Random Forest", category="model",
    description="Ensemble of decision trees",
    inputs=[Port("X_train", "X_train"), Port("y_train", "y_train"), Port("X_val", "X_val", optional=True), Port("y_val", "y_val", optional=True), Port("hp_config", "hpconfig", optional=True)],
    outputs=[Port("model", "model")],
    fields={
        "n_estimators": ui("Estimators"),
        "max_depth": ui("Max Depth"),
        "max_features": ui("Max Features"),
        "random_state": ui("Random Seed"),
    },
    code=EXPORT["rf"],
)
class RfHandler:
    class Config(BaseModel):
        n_estimators: int = 100
        max_depth: int = 10
        max_features: Literal["sqrt", "log2"] = "sqrt"
        random_state: int = 42

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        X_train: pd.DataFrame = ctx.inputs[0]
        y_train: pd.Series = ctx.inputs[1]
        model, preview = _fit_or_tune(
            X_train, y_train,
            RandomForestClassifier(
                n_estimators=cfg.n_estimators,
                max_depth=cfg.max_depth,
                max_features=cfg.max_features,
                random_state=cfg.random_state,
            ),
            ctx,
        )
        return HandlerResult(outputs=[model], preview=preview)


@node(
    "dtree", label="Decision Tree", category="model",
    description="Decision tree classifier/regressor",
    inputs=[Port("X_train", "X_train"), Port("y_train", "y_train"), Port("X_val", "X_val", optional=True), Port("y_val", "y_val", optional=True), Port("hp_config", "hpconfig", optional=True)],
    outputs=[Port("model", "model")],
    fields={
        "max_depth": ui("Max Depth"),
        "min_samples_split": ui("Min Samples Split"),
        "criterion": ui(),
    },
    code=EXPORT["dtree"],
)
class DtreeHandler:
    class Config(BaseModel):
        max_depth: int = 5
        min_samples_split: int = 2
        criterion: Literal["gini", "entropy"] = "gini"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        X_train: pd.DataFrame = ctx.inputs[0]
        y_train: pd.Series = ctx.inputs[1]
        model, preview = _fit_or_tune(
            X_train, y_train,
            DecisionTreeClassifier(
                max_depth=cfg.max_depth,
                min_samples_split=cfg.min_samples_split,
                criterion=cfg.criterion,
                random_state=42,  # ties between equally good splits are broken randomly otherwise
            ),
            ctx,
        )
        return HandlerResult(outputs=[model], preview=preview)


@node(
    "xgb", label="XGBoost", category="model",
    description="Gradient boosting — high performance",
    inputs=[Port("X_train", "X_train"), Port("y_train", "y_train"), Port("X_val", "X_val", optional=True), Port("y_val", "y_val", optional=True), Port("hp_config", "hpconfig", optional=True)],
    outputs=[Port("model", "model")],
    fields={
        "n_estimators": ui("Estimators"),
        "learning_rate": ui("Learning Rate"),
        "max_depth": ui("Max Depth"),
        "subsample": ui(),
    },
    code=EXPORT["xgb"],
)
class XgbHandler:
    class Config(BaseModel):
        n_estimators: int = 100
        learning_rate: float = 0.1
        max_depth: int = 6
        subsample: float = 0.8

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        try:
            from xgboost import XGBClassifier
        except ImportError:
            raise ImportError("xgboost is required: pip install xgboost")
        X_train: pd.DataFrame = ctx.inputs[0]
        y_train: pd.Series = ctx.inputs[1]
        model, preview = _fit_or_tune(
            X_train, y_train,
            XGBClassifier(
                n_estimators=cfg.n_estimators,
                learning_rate=cfg.learning_rate,
                max_depth=cfg.max_depth,
                subsample=cfg.subsample,
                eval_metric="logloss",
                verbosity=0,
            ),
            ctx,
        )
        return HandlerResult(outputs=[model], preview=preview)


@node(
    "svm", label="Support Vector Machine", category="model",
    description="SVM for classification or regression",
    inputs=[Port("X_train", "X_train"), Port("y_train", "y_train"), Port("X_val", "X_val", optional=True), Port("y_val", "y_val", optional=True), Port("hp_config", "hpconfig", optional=True)],
    outputs=[Port("model", "model")],
    fields={
        "C": ui(),
        "kernel": ui(),
        "gamma": ui(),
    },
    code=EXPORT["svm"],
)
class SvmHandler:
    class Config(BaseModel):
        C: float = 1.0
        kernel: Literal["rbf", "linear", "poly", "sigmoid"] = "rbf"
        gamma: Literal["scale", "auto"] = "scale"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        X_train: pd.DataFrame = ctx.inputs[0]
        y_train: pd.Series = ctx.inputs[1]
        model, preview = _fit_or_tune(
            X_train, y_train,
            SVC(C=cfg.C, kernel=cfg.kernel, gamma=cfg.gamma, probability=True, random_state=42),
            ctx,
        )
        return HandlerResult(outputs=[model], preview=preview)


@node(
    "knn", label="KNN", category="model",
    description="K-Nearest Neighbors",
    inputs=[Port("X_train", "X_train"), Port("y_train", "y_train"), Port("X_val", "X_val", optional=True), Port("y_val", "y_val", optional=True), Port("hp_config", "hpconfig", optional=True)],
    outputs=[Port("model", "model")],
    fields={
        "n_neighbors": ui("Neighbors"),
        "metric": ui(),
        "weights": ui(),
    },
    code=EXPORT["knn"],
)
class KnnHandler:
    class Config(BaseModel):
        n_neighbors: int = 5
        metric: Literal["euclidean", "manhattan", "cosine"] = "euclidean"
        weights: Literal["uniform", "distance"] = "uniform"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        X_train: pd.DataFrame = ctx.inputs[0]
        y_train: pd.Series = ctx.inputs[1]
        model, preview = _fit_or_tune(
            X_train, y_train,
            KNeighborsClassifier(
                n_neighbors=cfg.n_neighbors,
                metric=cfg.metric,
                weights=cfg.weights,
            ),
            ctx,
        )
        return HandlerResult(outputs=[model], preview=preview)


@node(
    "nb", label="Naive Bayes", category="model",
    description="Probabilistic classifier",
    inputs=[Port("X_train", "X_train"), Port("y_train", "y_train"), Port("X_val", "X_val", optional=True), Port("y_val", "y_val", optional=True), Port("hp_config", "hpconfig", optional=True)],
    outputs=[Port("model", "model")],
    fields={
        "variant": ui(),
        "var_smoothing": ui("Var Smoothing"),
    },
    code=EXPORT["nb"],
)
class NbHandler:
    class Config(BaseModel):
        variant: Literal["GaussianNB", "MultinomialNB", "BernoulliNB"] = "GaussianNB"
        var_smoothing: float = 1e-9

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        X_train: pd.DataFrame = ctx.inputs[0]
        y_train: pd.Series = ctx.inputs[1]
        if cfg.variant == "MultinomialNB":
            clf = MultinomialNB()
        elif cfg.variant == "BernoulliNB":
            clf = BernoulliNB()
        else:
            clf = GaussianNB(var_smoothing=cfg.var_smoothing)
        model, preview = _fit_or_tune(X_train, y_train, clf, ctx)
        return HandlerResult(outputs=[model], preview=preview)


@node(
    "mlp", label="Neural Network (MLP)", category="model",
    description="Multilayer perceptron",
    inputs=[Port("X_train", "X_train"), Port("y_train", "y_train"), Port("X_val", "X_val", optional=True), Port("y_val", "y_val", optional=True), Port("hp_config", "hpconfig", optional=True)],
    outputs=[Port("model", "model")],
    fields={
        "layers": ui("Hidden Layers"),
        "activation": ui(),
        "lr": ui("Learning Rate"),
        "epochs": ui(),
        "batch_size": ui("Batch Size"),
    },
    code=EXPORT["mlp"],
)
class MlpHandler:
    class Config(BaseModel):
        layers: str = "128, 64, 32"
        activation: Literal["relu", "tanh", "sigmoid"] = "relu"
        lr: float = 0.001
        epochs: int = 100
        batch_size: int = 32

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        X_train: pd.DataFrame = ctx.inputs[0]
        y_train: pd.Series = ctx.inputs[1]
        hidden = tuple(int(x.strip()) for x in cfg.layers.split(",") if x.strip())
        act = "logistic" if cfg.activation == "sigmoid" else cfg.activation
        model, preview = _fit_or_tune(
            X_train, y_train,
            MLPClassifier(
                hidden_layer_sizes=hidden,
                activation=act,
                learning_rate_init=cfg.lr,
                max_iter=cfg.epochs,
                batch_size=cfg.batch_size,
                random_state=42,
            ),
            ctx,
        )
        return HandlerResult(outputs=[model], preview=preview)


# ── REGRESSION MODELS ─────────────────────────────────────────────────────────

@node(
    "ridge", label="Ridge Regression", category="model",
    description="L2-regularized linear regression",
    inputs=[Port("X_train", "X_train"), Port("y_train", "y_train"), Port("X_val", "X_val", optional=True), Port("y_val", "y_val", optional=True), Port("hp_config", "hpconfig", optional=True)],
    outputs=[Port("model", "model")],
    fields={
        "alpha": ui("Alpha (Regularization)"),
        "fit_intercept": ui("Fit Intercept"),
    },
    code=EXPORT["ridge"],
)
class RidgeHandler:
    class Config(BaseModel):
        alpha: float = 1.0
        fit_intercept: bool = True

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        X_train: pd.DataFrame = ctx.inputs[0]
        y_train: pd.Series = ctx.inputs[1]
        model, preview = _fit_or_tune(
            X_train, y_train,
            Ridge(alpha=cfg.alpha, fit_intercept=cfg.fit_intercept),
            ctx,
        )
        return HandlerResult(outputs=[model], preview=preview)


@node(
    "lasso", label="Lasso Regression", category="model",
    description="L1-regularized regression — performs feature selection",
    inputs=[Port("X_train", "X_train"), Port("y_train", "y_train"), Port("X_val", "X_val", optional=True), Port("y_val", "y_val", optional=True), Port("hp_config", "hpconfig", optional=True)],
    outputs=[Port("model", "model")],
    fields={
        "alpha": ui("Alpha (Regularization)"),
        "max_iter": ui("Max Iterations"),
    },
    code=EXPORT["lasso"],
)
class LassoHandler:
    class Config(BaseModel):
        alpha: float = 1.0
        max_iter: int = 1000

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        X_train: pd.DataFrame = ctx.inputs[0]
        y_train: pd.Series = ctx.inputs[1]
        model, preview = _fit_or_tune(
            X_train, y_train,
            Lasso(alpha=cfg.alpha, max_iter=cfg.max_iter),
            ctx,
        )
        return HandlerResult(outputs=[model], preview=preview)


@node(
    "rf_reg", label="Random Forest Regressor", category="model",
    description="Ensemble of decision trees for regression",
    inputs=[Port("X_train", "X_train"), Port("y_train", "y_train"), Port("X_val", "X_val", optional=True), Port("y_val", "y_val", optional=True), Port("hp_config", "hpconfig", optional=True)],
    outputs=[Port("model", "model")],
    fields={
        "n_estimators": ui("Estimators"),
        "max_depth": ui("Max Depth"),
        "max_features": ui("Max Features"),
        "random_state": ui("Random Seed"),
    },
    code=EXPORT["rf_reg"],
)
class RfRegHandler:
    class Config(BaseModel):
        n_estimators: int = 100
        max_depth: int = 10
        max_features: Literal["sqrt", "log2"] = "sqrt"
        random_state: int = 42

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        X_train: pd.DataFrame = ctx.inputs[0]
        y_train: pd.Series = ctx.inputs[1]
        model, preview = _fit_or_tune(
            X_train, y_train,
            RandomForestRegressor(
                n_estimators=cfg.n_estimators,
                max_depth=cfg.max_depth,
                max_features=cfg.max_features,
                random_state=cfg.random_state,
            ),
            ctx,
        )
        return HandlerResult(outputs=[model], preview=preview)


@node(
    "xgb_reg", label="XGBoost Regressor", category="model",
    description="Gradient boosting for regression — high performance",
    inputs=[Port("X_train", "X_train"), Port("y_train", "y_train"), Port("X_val", "X_val", optional=True), Port("y_val", "y_val", optional=True), Port("hp_config", "hpconfig", optional=True)],
    outputs=[Port("model", "model")],
    fields={
        "n_estimators": ui("Estimators"),
        "learning_rate": ui("Learning Rate"),
        "max_depth": ui("Max Depth"),
        "subsample": ui(),
    },
    code=EXPORT["xgb_reg"],
)
class XgbRegHandler:
    class Config(BaseModel):
        n_estimators: int = 100
        learning_rate: float = 0.1
        max_depth: int = 6
        subsample: float = 0.8

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        try:
            from xgboost import XGBRegressor
        except ImportError:
            raise ImportError("xgboost is required: pip install xgboost")
        X_train: pd.DataFrame = ctx.inputs[0]
        y_train: pd.Series = ctx.inputs[1]
        model, preview = _fit_or_tune(
            X_train, y_train,
            XGBRegressor(
                n_estimators=cfg.n_estimators,
                learning_rate=cfg.learning_rate,
                max_depth=cfg.max_depth,
                subsample=cfg.subsample,
                verbosity=0,
            ),
            ctx,
        )
        return HandlerResult(outputs=[model], preview=preview)


@node(
    "dtree_reg", label="Decision Tree Regressor", category="model",
    description="Decision tree for regression tasks",
    inputs=[Port("X_train", "X_train"), Port("y_train", "y_train"), Port("X_val", "X_val", optional=True), Port("y_val", "y_val", optional=True), Port("hp_config", "hpconfig", optional=True)],
    outputs=[Port("model", "model")],
    fields={
        "max_depth": ui("Max Depth"),
        "min_samples_split": ui("Min Samples Split"),
        "criterion": ui(),
    },
    code=EXPORT["dtree_reg"],
)
class DtreeRegHandler:
    class Config(BaseModel):
        max_depth: int = 5
        min_samples_split: int = 2
        criterion: Literal["squared_error", "absolute_error", "friedman_mse"] = "squared_error"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        X_train: pd.DataFrame = ctx.inputs[0]
        y_train: pd.Series = ctx.inputs[1]
        model, preview = _fit_or_tune(
            X_train, y_train,
            DecisionTreeRegressor(
                max_depth=cfg.max_depth,
                min_samples_split=cfg.min_samples_split,
                criterion=cfg.criterion,
                random_state=42,  # ties between equally good splits are broken randomly otherwise
            ),
            ctx,
        )
        return HandlerResult(outputs=[model], preview=preview)


@node(
    "svr", label="Support Vector Regressor", category="model",
    description="SVR for regression tasks",
    inputs=[Port("X_train", "X_train"), Port("y_train", "y_train"), Port("X_val", "X_val", optional=True), Port("y_val", "y_val", optional=True), Port("hp_config", "hpconfig", optional=True)],
    outputs=[Port("model", "model")],
    fields={
        "C": ui(),
        "kernel": ui(),
        "epsilon": ui(),
        "gamma": ui(),
    },
    code=EXPORT["svr"],
)
class SvrHandler:
    class Config(BaseModel):
        C: float = 1.0
        kernel: Literal["rbf", "linear", "poly", "sigmoid"] = "rbf"
        epsilon: float = 0.1
        gamma: Literal["scale", "auto"] = "scale"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        X_train: pd.DataFrame = ctx.inputs[0]
        y_train: pd.Series = ctx.inputs[1]
        model, preview = _fit_or_tune(
            X_train, y_train,
            SVR(C=cfg.C, kernel=cfg.kernel, epsilon=cfg.epsilon, gamma=cfg.gamma),
            ctx,
        )
        return HandlerResult(outputs=[model], preview=preview)


@node(
    "knn_reg", label="KNN Regressor", category="model",
    description="K-Nearest Neighbors for regression",
    inputs=[Port("X_train", "X_train"), Port("y_train", "y_train"), Port("X_val", "X_val", optional=True), Port("y_val", "y_val", optional=True), Port("hp_config", "hpconfig", optional=True)],
    outputs=[Port("model", "model")],
    fields={
        "n_neighbors": ui("Neighbors"),
        "metric": ui(),
        "weights": ui(),
    },
    code=EXPORT["knn_reg"],
)
class KnnRegHandler:
    class Config(BaseModel):
        n_neighbors: int = 5
        metric: Literal["euclidean", "manhattan", "cosine"] = "euclidean"
        weights: Literal["uniform", "distance"] = "uniform"

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        X_train: pd.DataFrame = ctx.inputs[0]
        y_train: pd.Series = ctx.inputs[1]
        model, preview = _fit_or_tune(
            X_train, y_train,
            KNeighborsRegressor(
                n_neighbors=cfg.n_neighbors,
                metric=cfg.metric,
                weights=cfg.weights,
            ),
            ctx,
        )
        return HandlerResult(outputs=[model], preview=preview)


@node(
    "mlp_reg", label="Neural Network Regressor", category="model",
    description="Multilayer perceptron for regression",
    inputs=[Port("X_train", "X_train"), Port("y_train", "y_train"), Port("X_val", "X_val", optional=True), Port("y_val", "y_val", optional=True), Port("hp_config", "hpconfig", optional=True)],
    outputs=[Port("model", "model")],
    fields={
        "layers": ui("Hidden Layers"),
        "activation": ui(),
        "lr": ui("Learning Rate"),
        "epochs": ui(),
        "batch_size": ui("Batch Size"),
    },
    code=EXPORT["mlp_reg"],
)
class MlpRegHandler:
    class Config(BaseModel):
        layers: str = "128, 64, 32"
        activation: Literal["relu", "tanh", "sigmoid"] = "relu"
        lr: float = 0.001
        epochs: int = 100
        batch_size: int = 32

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        X_train: pd.DataFrame = ctx.inputs[0]
        y_train: pd.Series = ctx.inputs[1]
        hidden = tuple(int(x.strip()) for x in cfg.layers.split(",") if x.strip())
        act = "logistic" if cfg.activation == "sigmoid" else cfg.activation
        model, preview = _fit_or_tune(
            X_train, y_train,
            MLPRegressor(
                hidden_layer_sizes=hidden,
                activation=act,
                learning_rate_init=cfg.lr,
                max_iter=cfg.epochs,
                batch_size=cfg.batch_size,
                random_state=42,
            ),
            ctx,
        )
        return HandlerResult(outputs=[model], preview=preview)


@node(
    "gb_reg", label="Gradient Boosting Regressor", category="model",
    description="Gradient boosting ensemble for regression (scikit-learn)",
    inputs=[Port("X_train", "X_train"), Port("y_train", "y_train"), Port("X_val", "X_val", optional=True), Port("y_val", "y_val", optional=True), Port("hp_config", "hpconfig", optional=True)],
    outputs=[Port("model", "model")],
    fields={
        "n_estimators": ui("Estimators"),
        "learning_rate": ui("Learning Rate"),
        "max_depth": ui("Max Depth"),
        "subsample": ui(),
        "random_state": ui("Random Seed"),
    },
    code=EXPORT["gb_reg"],
)
class GbRegHandler:
    class Config(BaseModel):
        n_estimators: int = 100
        learning_rate: float = 0.1
        max_depth: int = 3
        subsample: float = 1.0
        random_state: int = 42

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        X_train: pd.DataFrame = ctx.inputs[0]
        y_train: pd.Series = ctx.inputs[1]
        model, preview = _fit_or_tune(
            X_train, y_train,
            GradientBoostingRegressor(
                n_estimators=cfg.n_estimators,
                learning_rate=cfg.learning_rate,
                max_depth=cfg.max_depth,
                subsample=cfg.subsample,
                random_state=cfg.random_state,
            ),
            ctx,
        )
        return HandlerResult(outputs=[model], preview=preview)
