"""PDF validation report (requires matplotlib)."""

from __future__ import annotations

import io

import numpy as np

from .i18n import t as tr
from .model import Show
from .validation import ValidationReport, validate_show

__all__ = ("render_report_pdf",)


def render_report_pdf(
    show: Show, report: ValidationReport | None = None, *, dt: float = 0.25
) -> bytes:
    """Renders a multi-page PDF with the validation summary, safety
    time series and a top-down / front view of the trajectories."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_pdf import PdfPages
    except ImportError as ex:  # pragma: no cover - optional dependency
        raise RuntimeError("PDF reports require matplotlib: pip install murmura[plot]") from ex

    report = report or validate_show(show, dt=dt)
    lim = report.limits
    s = report.series
    t = s["time"]
    buffer = io.BytesIO()

    with PdfPages(buffer) as pdf:
        # Page 1: summary
        fig = plt.figure(figsize=(8.27, 11.69))
        fig.text(
            0.08,
            0.95,
            tr("Validation report - {title}", title=show.title),
            fontsize=16,
            weight="bold",
        )
        fig.text(
            0.08,
            0.92,
            tr("PASSED") if report.passed else tr("FAILED"),
            fontsize=13,
            color="#1b7f3b" if report.passed else "#b3261e",
            weight="bold",
        )
        fig.text(0.08, 0.88, report.summary(), fontsize=9, family="monospace", va="top")
        if report.violations:
            listing = "\n".join(v.describe() for v in report.violations[:40])
            fig.text(
                0.08,
                0.55,
                tr("First violations:") + "\n" + listing,
                fontsize=7,
                family="monospace",
                va="top",
            )
        pdf.savefig(fig)
        plt.close(fig)

        # Page 2: time series
        fig, axes = plt.subplots(5, 1, figsize=(8.27, 11.69), sharex=True)
        panels = [
            ("maxAltitude", tr("Max altitude [m]"), lim.max_altitude),
            ("maxVelocityXY", tr("Max horizontal speed [m/s]"), lim.max_velocity_xy),
            ("maxVelocityZ", tr("Max vertical speed [m/s]"), lim.max_velocity_z),
            (
                "maxAcceleration",
                tr("Max acceleration [m/s²]"),
                max(lim.max_acceleration_xy, lim.max_acceleration_z),
            ),
            ("minDistance", tr("Min distance (airborne) [m]"), lim.min_distance),
        ]
        for ax, (key, label, limit) in zip(axes, panels):
            values = np.where(np.isfinite(s[key]), s[key], np.nan)
            ax.plot(t, values, lw=1.0, color="#2a5bd7")
            ax.axhline(limit, color="#b3261e", lw=0.8, ls="--")
            ax.set_ylabel(label, fontsize=8)
            ax.grid(alpha=0.3)
            for name, (a, b) in show.segments.items():
                ax.axvspan(
                    a,
                    b,
                    alpha=0.06,
                    color={"takeoff": "g", "show": "b", "landing": "orange"}.get(name, "gray"),
                )
        axes[-1].set_xlabel(tr("Time [s]"))
        fig.suptitle(tr("Safety envelope over time"))
        fig.tight_layout()
        pdf.savefig(fig)
        plt.close(fig)

        # Page 3: projections
        fig, (top, front) = plt.subplots(2, 1, figsize=(8.27, 11.69))
        times = np.arange(min(0.0, show.start_time), show.end_time + 0.5, 0.5)
        for drone in show.drones:
            if not drone.trajectory:
                continue
            p = drone.trajectory.position_at(times)
            top.plot(p[:, 0], p[:, 1], lw=0.3, alpha=0.6)
            front.plot(p[:, 0], p[:, 2], lw=0.3, alpha=0.6)
        top.set_title(tr("Top view (X / Y)"))
        front.set_title(tr("Front view (X / Z)"))
        for ax in (top, front):
            ax.set_aspect("equal", adjustable="datalim")
            ax.grid(alpha=0.3)
        fig.tight_layout()
        pdf.savefig(fig)
        plt.close(fig)

    return buffer.getvalue()
