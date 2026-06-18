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

from athena.core.registry import register
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


@register("lin_reg")
class LinRegHandler:
    class Config(BaseModel):
        fit_intercept: bool = True

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        X_train: pd.DataFrame = ctx.inputs[0]
        y_train: pd.Series = ctx.inputs[1]
        model, preview = _fit_or_tune(X_train, y_train, LinearRegression(fit_intercept=cfg.fit_intercept), ctx)
        return HandlerResult(outputs=[model], preview=preview)


@register("log_reg")
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


@register("rf")
class RfHandler:
    class Config(BaseModel):
        n_estimators: int = 100
        max_depth: int = 10
        max_features: str = "sqrt"
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


@register("dtree")
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
            ),
            ctx,
        )
        return HandlerResult(outputs=[model], preview=preview)


@register("xgb")
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


@register("svm")
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
            SVC(C=cfg.C, kernel=cfg.kernel, gamma=cfg.gamma, probability=True),
            ctx,
        )
        return HandlerResult(outputs=[model], preview=preview)


@register("knn")
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


@register("nb")
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


@register("mlp")
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

@register("ridge")
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


@register("lasso")
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


@register("rf_reg")
class RfRegHandler:
    class Config(BaseModel):
        n_estimators: int = 100
        max_depth: int = 10
        max_features: str = "sqrt"
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


@register("xgb_reg")
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


@register("dtree_reg")
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
            ),
            ctx,
        )
        return HandlerResult(outputs=[model], preview=preview)


@register("svr")
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


@register("knn_reg")
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


@register("mlp_reg")
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


@register("gb_reg")
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
