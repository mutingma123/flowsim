# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

The initial padding fixes the reported case, but Autoscale can restore the Firefox click defect. Runtime verification was blocked because Pixi could not acquire its installation lock on the read-only filesystem.

Findings:
- [medium] Autoscale discards the padding and restores the zero-edge defect (flowsim/reporting.py:575)
  The explicit range leaves yaxis.rangemode="tozero" inherited from style(). The dashboard exposes Plotly's default Autoscale button, whose bundled implementation sets axis.autorange=true. This discards the padded range and restores the original zero-boundary behavior. Based on the brief's Firefox reproduction, zero-valued points then become unclickable at their centres again. The changed browser tests only click before autoscaling, so they can pass while this defect remains. This interaction was confirmed by source inspection, not browser execution.
  Recommendation: Alongside the explicit initial range, set yaxis.rangemode="normal" and autorangeoptions.include=[0] so subsequent autoscaling retains padding around zero. The explicit range preserves the intended initial scale; user-requested autoscaling may produce a different padded scale. Extend the Firefox browser regression to activate Autoscale and then click the centre of a zero-valued point after a location change. Reject merely hiding Autoscale in dashboard.html because that removes useful interaction and leaves returned figures vulnerable.

Next steps:
- Fix the autorange fallback and verify zero-centre clicks after Autoscale in both browser engines.
