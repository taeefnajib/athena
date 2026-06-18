from pydantic import BaseModel
from typing import Literal
import numpy as np
import pandas as pd

from athena.core.registry import register
from athena.core.handler import ExecutionContext, HandlerResult
from athena.schemas.artifacts import ModelPreview


class _VotingEnsemble:
    """Wraps pre-fitted estimators for soft/hard voting."""
    def __init__(self, estimators: list, voting: str = "soft", weights: list | None = None):
        self.estimators = estimators
        self.voting = voting
        self.weights = weights

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        if self.voting == "soft" and all(hasattr(e, "predict_proba") for e in self.estimators):
            return np.argmax(self.predict_proba(X), axis=1)
        preds = np.array([e.predict(X) for e in self.estimators])
        # majority vote per sample
        return np.apply_along_axis(lambda col: np.bincount(col.astype(int)).argmax(), axis=0, arr=preds)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        probas = np.array([e.predict_proba(X) for e in self.estimators])
        if self.weights:
            w = np.array(self.weights[:len(self.estimators)], dtype=float)
            w /= w.sum()
            return np.average(probas, axis=0, weights=w)
        return probas.mean(axis=0)

    def __repr__(self) -> str:
        names = [type(e).__name__ for e in self.estimators]
        return f"VotingEnsemble(models={names}, voting={self.voting})"


@register("voting")
class VotingHandler:
    class Config(BaseModel):
        voting: Literal["hard", "soft"] = "soft"
        weights: str = ""

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        models = [ctx.inputs[i] for i in range(min(5, len(ctx.inputs))) if ctx.inputs[i] is not None]
        if len(models) < 2:
            raise ValueError("Voting ensemble requires at least 2 connected model inputs")
        weights = [float(w) for w in cfg.weights.split(",") if w.strip()] if cfg.weights.strip() else None
        ensemble = _VotingEnsemble(models, voting=cfg.voting, weights=weights)
        ctx.logger.info("Voting ensemble created", voting=cfg.voting, n_models=len(models))
        return HandlerResult(outputs=[ensemble], preview=ModelPreview(summary=repr(ensemble)))


class _StackingEnsemble:
    """Stacking ensemble: base models predict, meta-learner combines their outputs."""
    def __init__(self, base_models: list, meta_model):
        self.base_models = base_models
        self.meta_model = meta_model
        self._fitted = False

    def _meta_features(self, X: pd.DataFrame) -> np.ndarray:
        parts = []
        for m in self.base_models:
            if hasattr(m, "predict_proba"):
                parts.append(m.predict_proba(X))
            else:
                parts.append(m.predict(X).reshape(-1, 1))
        return np.hstack(parts)

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "_StackingEnsemble":
        meta_X = self._meta_features(X)
        self.meta_model.fit(meta_X, y)
        self._fitted = True
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        if not self._fitted:
            raise ValueError(
                "Stacking meta-learner is not fitted — connect X_train and y_train to the Stacking node."
            )
        return self.meta_model.predict(self._meta_features(X))

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        if not self._fitted:
            raise ValueError(
                "Stacking meta-learner is not fitted — connect X_train and y_train to the Stacking node."
            )
        if hasattr(self.meta_model, "predict_proba"):
            return self.meta_model.predict_proba(self._meta_features(X))
        raise AttributeError("meta_model does not support predict_proba")

    def __repr__(self) -> str:
        names = [type(m).__name__ for m in self.base_models]
        status = "fitted" if self._fitted else "unfitted"
        return f"StackingEnsemble(base={names}, meta={type(self.meta_model).__name__}, {status})"


@register("stacking")
class StackingHandler:
    class Config(BaseModel):
        meta: Literal["LogisticRegression", "LinearRegression"] = "LogisticRegression"
        cv: int = 5

    def __call__(self, ctx: ExecutionContext) -> HandlerResult:
        cfg = self.Config(**ctx.config)
        # Ports 0-4: base models (some may be None/unconnected)
        models = [ctx.inputs[i] for i in range(min(5, len(ctx.inputs))) if ctx.inputs[i] is not None]
        if len(models) < 2:
            raise ValueError("Stacking ensemble requires at least 2 connected model inputs")

        # Ports 5 and 6: X_train and y_train — required to fit the meta-learner
        X_train = ctx.inputs[5] if len(ctx.inputs) > 5 else None
        y_train = ctx.inputs[6] if len(ctx.inputs) > 6 else None
        if X_train is None or y_train is None:
            raise ValueError(
                "Stacking requires X_train (port 6) and y_train (port 7) to fit the meta-learner. "
                "Connect them from your split node."
            )

        if cfg.meta == "LogisticRegression":
            from sklearn.linear_model import LogisticRegression
            meta = LogisticRegression(max_iter=200)
        else:
            from sklearn.linear_model import LinearRegression
            meta = LinearRegression()

        ensemble = _StackingEnsemble(models, meta)
        ctx.logger.info("Fitting stacking meta-learner", meta=cfg.meta, samples=len(X_train), n_models=len(models))
        ensemble.fit(X_train, y_train)
        ctx.logger.info("Stacking ensemble ready", n_models=len(models))
        return HandlerResult(outputs=[ensemble], preview=ModelPreview(summary=repr(ensemble)))


def _stub(type_name: str):
    @register(type_name)
    class StubHandler:
        def __call__(self, ctx: ExecutionContext) -> HandlerResult:
            raise NotImplementedError(f"{type_name} is not yet implemented in v1.")
    StubHandler.__name__ = f"{type_name.title().replace('_', '')}Handler"


_stub("blending")
