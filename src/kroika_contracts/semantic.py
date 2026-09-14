"""Cross-field rules that JSON Schema cannot express clearly."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .contract_io import validate_document
from .hashing import compute_input_hash


@dataclass(frozen=True, slots=True)
class SemanticIssue:
    code: str
    json_pointer: str
    message_ru: str


class SemanticContractError(ValueError):
    def __init__(self, issues: list[SemanticIssue]):
        self.issues = tuple(issues)
        super().__init__('; '.join(f'{issue.code} {issue.json_pointer}: {issue.message_ru}'
                                   for issue in issues))


def _add(issues: list[SemanticIssue], code: str, pointer: str, message: str) -> None:
    issues.append(SemanticIssue(code, pointer, message))


def _measurement_issues(
    measurements: Mapping[str, Any], garment_type: str | None = None,
    sleeve_type: str = 'sleeveless',
) -> list[SemanticIssue]:
    from .measurements import measurement_issues

    return [
        SemanticIssue(item.code, item.json_pointer, item.message_ru)
        for item in measurement_issues(measurements, garment_type, sleeve_type)
        if item.severity == 'blocking_error'
    ]


def validate_validation_report(report: Mapping[str, Any]) -> None:
    validate_document('validation-report', report)
    issues: list[SemanticIssue] = []
    blockers = [item for item in report['issues'] if item['severity'] == 'blocking_error']
    failed_checks = [item for item in report['checks'] if item['status'] == 'failed']
    if blockers and report['status'] != 'failed':
        _add(issues, 'REPORT_BLOCKER_STATUS', '/status',
             'При блокирующей ошибке отчёт должен иметь статус failed.')
    if failed_checks and report['status'] != 'failed':
        _add(issues, 'REPORT_FAILED_CHECK_STATUS', '/status',
             'При проваленной проверке отчёт должен иметь статус failed.')
    warnings = [item for item in report['issues'] if item['severity'] == 'warning']
    if report['status'] == 'passed' and warnings:
        _add(issues, 'REPORT_WARNING_STATUS', '/status',
             'При предупреждениях отчёт должен иметь статус warnings.')
    if report['status'] == 'failed' and not blockers and not failed_checks:
        _add(issues, 'REPORT_FAILURE_WITHOUT_CAUSE', '/issues',
             'Для статуса failed нужна блокирующая проблема или проваленная проверка.')
    if blockers and report['production_export_allowed']:
        _add(issues, 'REPORT_EXPORT_WITH_BLOCKER', '/production_export_allowed',
             'Производственный экспорт запрещён при блокирующих ошибках.')
    if report['production_export_allowed'] and report['method_validation_status'] != 'toile_verified':
        _add(issues, 'REPORT_METHOD_NOT_VERIFIED', '/method_validation_status',
             'Производственный экспорт разрешается только для toile_verified.')
    if issues:
        raise SemanticContractError(issues)


def validate_ai_analysis(analysis: Mapping[str, Any]) -> None:
    validate_document('ai-style-analysis', analysis)
    issues: list[SemanticIssue] = []
    sleeves = analysis['sleeves']
    if not sleeves['present'] and (sleeves['length'] != 'sleeveless'
                                   or sleeves['cuff'] != 'none'):
        _add(issues, 'AI_SLEEVE_CONTRADICTION', '/sleeves',
             'При отсутствии рукава длина должна быть sleeveless, а манжета none.')
    if sleeves['present'] and sleeves['length'] == 'sleeveless':
        _add(issues, 'AI_SLEEVE_CONTRADICTION', '/sleeves/length',
             'Рукав не может одновременно присутствовать и иметь значение sleeveless.')
    if analysis['status'] == 'ok' and analysis['garment_category'] == 'unknown':
        _add(issues, 'AI_UNKNOWN_CATEGORY_OK', '/garment_category',
             'Неизвестная категория не может иметь итоговый статус ok.')
    if analysis['status'] in {'needs_confirmation', 'insufficient_input'}:
        if not analysis['uncertainties'] and not analysis['targeted_questions']:
            _add(issues, 'AI_MISSING_CLARIFICATION', '/uncertainties',
                 'Нужно объяснить неопределённость или задать уточняющий вопрос.')
    if issues:
        raise SemanticContractError(issues)


def validate_engine_request(request: Mapping[str, Any]) -> None:
    validate_document('pattern-engine-request', request)
    issues: list[SemanticIssue] = []

    if request['input_hash'] != compute_input_hash(request):
        _add(issues, 'INPUT_HASH_MISMATCH', '/input_hash',
             'Контрольная сумма не соответствует нормализованным входам.')

    shares = request['fit_settings']['distribution']
    if abs(shares['front_share'] + shares['back_share'] - 1.0) > 1e-12:
        _add(issues, 'EASE_DISTRIBUTION_SUM', '/fit_settings/distribution',
             'Доли прибавки переда и спинки должны в сумме давать 1.')

    spec = request['garment_spec']
    issues.extend(_measurement_issues(
        request['body_measurements'], spec['garment_type'], spec['parameters']['sleeve']['type'],
    ))

    method = request['pattern_method']
    if (method['id'], method['version']) != ('kroika-gc-woven', '0.1.0'):
        _add(issues, 'METHOD_NOT_AVAILABLE', '/pattern_method',
             'Запрошенная версия методики отсутствует в текущем исследовательском комплекте.')

    fabric = request['fabric_properties']
    if fabric['structure'] != 'woven' or fabric['stability'] != 'stable':
        _add(issues, 'FABRIC_OUTSIDE_METHOD', '/fabric_properties',
             'Текущая методика исследуется только для стабильной неэластичной ткани.')
    if max(fabric['stretch_percent'].values()) > 5:
        _add(issues, 'FABRIC_STRETCH_OUTSIDE_METHOD', '/fabric_properties/stretch_percent',
             'Растяжимость выше 5% не входит в область текущей методики.')

    parameters = spec['parameters']
    expected_preset = {
        'fitted': 'woven_fitted_trial',
        'semi_fitted': 'woven_semi_fitted_trial',
    }.get(parameters['bodice_fit'])
    supported_variant = (
        spec['garment_type'] in {'dress', 'sundress'}
        and expected_preset is not None
        and request['fit_settings']['preset']['id'] == expected_preset
        and parameters['neckline']['type'] == 'round'
        and parameters['sleeve']['type'] == 'sleeveless'
        and parameters['skirt']['type'] == 'a_line'
        and parameters['closure']['type'] == 'zipper'
        and parameters['closure']['location'] == 'center_back'
        and parameters['finishing'] == {'neckline_facing': True, 'armhole_facing': True}
    )
    if not supported_variant:
        _add(
            issues, 'GARMENT_VARIANT_NOT_IMPLEMENTED', '/garment_spec/parameters',
            'Сейчас поддерживаются платье и сарафан без рукавов: круглая горловина, '
            'отрезная А-юбка, вытачки, обтачки и молния по центру спинки.',
        )

    if issues:
        raise SemanticContractError(issues)


def validate_project(project: Mapping[str, Any]) -> None:
    validate_document('pattern-project', project)
    from .measurements import measurement_issues

    sleeve_type = project['garment_spec']['parameters']['sleeve']['type']
    issues = [
        SemanticIssue(item.code, item.json_pointer, item.message_ru)
        for item in measurement_issues(
            project['body_measurements'], project['garment_spec']['garment_type'], sleeve_type,
        )
        if item.severity == 'blocking_error'
    ]
    if project['status'] != 'draft' and project['body_measurements']['status'] != 'ready':
        _add(
            issues, 'PROJECT_MEASUREMENTS_NOT_READY', '/body_measurements/status',
            'Проект нельзя подтвердить, пока обязательные мерки не заполнены.',
        )
    latest = project['latest_generation']
    if latest is not None:
        if latest['project_id'] != project['project_id']:
            _add(issues, 'PROJECT_GENERATION_ID_MISMATCH', '/latest_generation/project_id',
                 'Результат построения относится к другому проекту.')
        if latest['pattern_method'] != project['pattern_method']:
            _add(issues, 'PROJECT_METHOD_MISMATCH', '/latest_generation/pattern_method',
                 'Версия методики результата не совпадает с проектом.')
        try:
            validate_validation_report(latest['validation_report'])
        except SemanticContractError as exc:
            issues.extend(exc.issues)
        if latest['validation_report']['project_id'] != project['project_id']:
            _add(issues, 'PROJECT_REPORT_ID_MISMATCH',
                 '/latest_generation/validation_report/project_id',
                 'Отчёт проверки относится к другому проекту.')
        if latest['validation_report']['generation_id'] != latest['generation_id']:
            _add(issues, 'GENERATION_REPORT_ID_MISMATCH',
                 '/latest_generation/validation_report/generation_id',
                 'Отчёт проверки относится к другому результату построения.')
        if latest['validation_report']['input_hash'] != latest['input_hash']:
            _add(issues, 'GENERATION_REPORT_HASH_MISMATCH',
                 '/latest_generation/validation_report/input_hash',
                 'Отчёт и результат построения имеют разные входные контрольные суммы.')
        if project['generation_history']:
            summary = project['generation_history'][-1]
            expected_summary = {
                'generation_id': latest['generation_id'],
                'input_hash': latest['input_hash'],
                'engine_version': latest['engine_version'],
                'method_version': latest['pattern_method']['version'],
                'created_at': latest['created_at'],
                'status': latest['status'],
            }
            if summary != expected_summary:
                _add(issues, 'PROJECT_HISTORY_MISMATCH', '/generation_history',
                     'Последняя запись истории не соответствует текущему результату.')
        if project['status'] == 'generated' and latest['status'] != 'succeeded':
            _add(issues, 'PROJECT_GENERATED_WITHOUT_PATTERN', '/status',
                 'Статус generated требует успешного результата построения.')
        if (project['status'] == 'validation_failed'
                and latest['validation_report']['status'] != 'failed'):
            _add(issues, 'PROJECT_FAILURE_STATUS_MISMATCH', '/status',
                 'Статус validation_failed требует проваленного отчёта проверки.')
    if project['status'] == 'ready_for_production_export':
        if latest is None or not latest['validation_report']['production_export_allowed']:
            _add(issues, 'PROJECT_EXPORT_NOT_ALLOWED', '/status',
                 'Проект не прошёл условия производственного экспорта.')
    if issues:
        raise SemanticContractError(issues)
