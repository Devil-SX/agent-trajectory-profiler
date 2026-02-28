import { useMemo, useState, type ReactNode } from 'react';
import { getGlossaryEntry, type GlossaryMetricId } from '../i18n/glossary';
import { useI18n } from '../i18n';
import './MetricHelp.css';

interface MetricHelpProps {
  metricId: GlossaryMetricId;
}

export function MetricHelp({ metricId }: MetricHelpProps) {
  const { locale } = useI18n();
  const [open, setOpen] = useState(false);

  const entry = useMemo(() => getGlossaryEntry(metricId, locale), [locale, metricId]);
  const labels = locale === 'zh-CN'
    ? {
        formula: '公式',
        inputs: '输入来源',
        notes: '注意事项',
      }
    : {
        formula: 'Formula',
        inputs: 'Inputs',
        notes: 'Notes',
      };

  return (
    <span className="metric-help" data-metric-help={metricId}>
      <button
        type="button"
        className="metric-help__trigger"
        onClick={() => setOpen((prev) => !prev)}
        aria-label={locale === 'zh-CN' ? `${entry.term} 说明` : `${entry.term} help`}
        aria-expanded={open}
        title={entry.short}
      >
        ?
      </button>
      {open && (
        <div className="metric-help__panel" role="dialog" aria-label={`${entry.term} definition`}>
          <p className="metric-help__term">{entry.term}</p>
          <p className="metric-help__summary">{entry.definition}</p>
          <p>
            <strong>{labels.formula}:</strong> {entry.formula}
          </p>
          <p>
            <strong>{labels.inputs}:</strong> {entry.inputs}
          </p>
          <p>
            <strong>{labels.notes}:</strong> {entry.notes}
          </p>
          <button
            type="button"
            className="metric-help__close"
            onClick={() => setOpen(false)}
          >
            {entry.closeLabel}
          </button>
        </div>
      )}
    </span>
  );
}

interface MetricTermProps {
  metricId: GlossaryMetricId;
  children: ReactNode;
}

export function MetricTerm({ metricId, children }: MetricTermProps) {
  return (
    <span className="metric-term">
      {children}
      <MetricHelp metricId={metricId} />
    </span>
  );
}
