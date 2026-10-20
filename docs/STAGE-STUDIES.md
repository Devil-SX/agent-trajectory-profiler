# Stage segmentation research

The **研究统计** dashboard tab reads the same authenticated operations as Agents.
Discover `stage_study_list`, `stage_study_read`, `stage_study_stages` and
`stage_study_import` through runtime Help. Import requires `configure`; queries
and CSV exports require `read`. All snapshots are isolated by account.

`StageStudies` owns one additive `stage_studies` table in the existing domain DB.
Imports validate the original batch, saved analysis/source revisions, every
non-root task and exclusive operation membership. A stable mutation ID replays
the same payload; changed payloads require a new study identity. Imported labels
and audited frozen measurements do not change analyses or usage ledgers and do
not call a model. Private study payloads are not package assets.

Queries filter session, depth, leaf/parent, activity label, title and metric.
Direct metrics have exclusive operation ownership. Empty direct memberships
are excluded from resource coverage, whereas measured zero is retained. CSV
exports include `resource_metric_eligible` for the same coverage rule. Subtree metrics can overlap
between rows; aggregate resources use only selected nodes without a selected
ancestor. Nonadditive wall spans and prompt groups remain unknown in subtree
mode. Missing measurements remain null. Empty direct memberships do not imply
measured zero human effort.

Mutually exclusive effective primary labels apply the imported confidence
threshold. Secondary labels remain separately inspectable; their per-category
coverage uses all selected stages as denominator and can sum above 100%.
The model's mixed-activity probability concerns the labeled stage, whereas
operation-weighted subtree label entropy describes the composition of the
hierarchy. Neither is measured classification accuracy.

The summary reports session-level share means, sample variance and standard
deviation, plus 95% session-cluster percentile intervals (10,000 replicates,
fixed seed). Depth associations use Spearman ranks and 300 cluster replicates.
Less than two eligible sessions produces no interval. These exploratory
intervals do not account for label errors, segmentation errors or selection
bias. Model confidence, unavailable segmentation confidence, and unavailable
human gold accuracy are separate fields. Source and analysis revisions,
measurement hashes, model metadata and Jindu call/receipt IDs are retained.

`research.js` mounts only when the dashboard tab is selected. Advanced filters,
variance and hierarchy tables use the workbench disclosure pattern. Overview
charts retain confidence intervals and sample counts; active-time estimates
are visible by default alongside stage counts and the selected resource. The
independent active-time summary uses identical filters and study revision, with
its own total, valid sessions, missing coverage, session standard deviations and
cluster intervals. Active time is estimated from recorded event gaps, not LLM
request latency or human work time. Tool durations can overlap; wall spans include
waiting and interleaved tasks. paginated stage details
are fetched only when expanded. Summary and detail use the server's domain aggregation; immutable summary reads
are cached by account, study revision and filters. CSV exports preserve
unknowns and neutralize spreadsheet formula prefixes without editing stored
titles. Updating a source analysis does not mutate an imported study: the UI
reports changed analysis heads against the fixed research snapshot.
