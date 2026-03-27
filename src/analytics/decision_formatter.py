from __future__ import annotations


class RoleDecisionFormatter:
    def format(self, track_id: int, features, probabilities: dict) -> dict:
        ep = probabilities["employee_probability"]
        cp = probabilities["customer_probability"]
        up = probabilities["unknown_probability"]

        if ep >= 0.75:
            label = "employee"
        elif cp >= 0.70:
            label = "customer"
        else:
            label = "unknown"

        feature_map = features.__dict__
        sorted_signals = sorted(feature_map.items(), key=lambda kv: abs(kv[1]), reverse=True)
        top_signals = [k for k, _ in sorted_signals[:4]]

        return {
            "track_id": track_id,
            "role_label": label,
            "employee_probability": ep,
            "customer_probability": cp,
            "unknown_probability": up,
            "top_signals": top_signals,
            "reason_summary": ", ".join(top_signals),
        }
