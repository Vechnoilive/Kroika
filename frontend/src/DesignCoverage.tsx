import {buildDesignCoverage, evidenceCount} from './designCoverage';
import type {GarmentDesignIntent, PatternData, StyleAnalysis} from './types';

const DECISION_LABELS = {
  compiled: 'Есть в выкройке',
  excluded_by_user: 'Исключено вами',
  missing_evidence: 'Нет геометрического подтверждения',
  missing_from_plan: 'Потеряно между фото и планом',
} as const;

export function DesignCoverageSummary({
  intent,
  analysis,
  pattern,
  onEditDesign,
}: {
  intent: GarmentDesignIntent;
  analysis?: StyleAnalysis | null;
  pattern: PatternData;
  onEditDesign?: () => void;
}) {
  const report = buildDesignCoverage(intent, analysis, pattern.design_coverage);
  return (
    <section
      className={`coverage-summary coverage-summary--${report.complete ? 'complete' : 'incomplete'}`}
      aria-labelledby="coverage-title"
    >
      <header>
        <div>
          <p className="eyebrow">Сопоставление с фото</p>
          <h3 id="coverage-title">
            {report.complete
              ? `Фасон покрыт: ${report.compiledCount} из ${report.requiredCount}`
              : `Нужно исправить покрытие: ${report.missingCount}`}
          </h3>
          <p>
            Найденные на фото и добавленные вручную детали сверены с реальными
            деталями, линиями, соединениями и операциями выкройки.
          </p>
        </div>
        <span className="coverage-summary__score" aria-label="Покрытие фасона">
          {report.compiledCount}/{report.requiredCount}
        </span>
      </header>

      <dl className="coverage-stats">
        <div><dt>С фото</dt><dd>{report.photoCount}</dd></div>
        <div><dt>В выкройке</dt><dd>{report.compiledCount}</dd></div>
        <div><dt>Исключено</dt><dd>{report.excludedCount}</dd></div>
        <div><dt>Без покрытия</dt><dd>{report.missingCount}</dd></div>
      </dl>

      <ul className="coverage-list">
        {report.entries.map((entry) => {
          const count = evidenceCount(entry.evidence);
          const evidenceIds = entry.evidence
            ? Object.values(entry.evidence).flat()
            : [];
          return (
            <li key={`${entry.sourceKind}-${entry.sourceId}`} className={`coverage-entry coverage-entry--${entry.decision}`}>
              <div>
                <span className="coverage-entry__origin">
                  {entry.origin === 'photo' ? 'С фото' : 'Добавлено вручную'}
                </span>
                <strong>{entry.label}</strong>
                <small>{DECISION_LABELS[entry.decision]}</small>
              </div>
              {count > 0 && (
                <details>
                  <summary>Доказательств: {count}</summary>
                  <code>{evidenceIds.join(', ')}</code>
                </details>
              )}
            </li>
          );
        })}
      </ul>

      <div className="coverage-summary__footer">
        <p>
          Цифровое покрытие подтверждает состав выкройки, но не посадку. Проверка
          масштаба, бумажная сборка, эксперт и макет остаются отдельными gates.
        </p>
        {onEditDesign && (
          <button type="button" className="secondary-button" onClick={onEditDesign}>
            Вернуться к деталям фасона
          </button>
        )}
      </div>
    </section>
  );
}
