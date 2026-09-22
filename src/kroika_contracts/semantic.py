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
    design = analysis.get('design_features')
    if isinstance(design, Mapping):
        element_ids = [item['element_id'] for item in design['elements']]
        layer_ids = [item['layer_id'] for item in design['layers']]
        if len(element_ids) != len(set(element_ids)):
            _add(issues, 'AI_DESIGN_ELEMENT_ID_DUPLICATE', '/design_features/elements',
                 'Каждая найденная деталь должна иметь отдельный element_id.')
        if len(layer_ids) != len(set(layer_ids)):
            _add(issues, 'AI_DESIGN_LAYER_ID_DUPLICATE', '/design_features/layers',
                 'Каждый слой изделия должен иметь отдельный layer_id.')
        if sum(item['role'] == 'main' for item in design['layers']) != 1:
            _add(issues, 'AI_DESIGN_MAIN_LAYER_COUNT', '/design_features/layers',
                 'В визуальном разборе должен быть ровно один основной слой.')
        uncertain_features = [
            item for group in ('elements', 'layers') for item in design[group]
            if item['requires_confirmation']
        ]
        if uncertain_features and not analysis['targeted_questions']:
            _add(issues, 'AI_DESIGN_QUESTION_MISSING', '/targeted_questions',
                 'Для сомнительной детали или слоя нужен точный вопрос пользователю.')
    if issues:
        raise SemanticContractError(issues)


def _validate_design_intent(
    spec: Mapping[str, Any], issues: list[SemanticIssue], *, require_ready: bool,
) -> None:
    intent = spec.get('design_intent')
    if not isinstance(intent, Mapping):
        return
    review_aware = 'review_status' in intent
    has_review_fields = (
        any(key in intent for key in ('reviewed_at', 'question_answers'))
        or any(
            key in item
            for group in ('elements', 'layers')
            for item in intent[group]
            for key in ('included', 'confirmed_by_user', 'dimensions_mm')
        )
        or 'confirmed_by_user' in intent['proportions']
    )
    if has_review_fields and not review_aware:
        _add(issues, 'DESIGN_REVIEW_STATUS_MISSING',
             '/garment_spec/design_intent/review_status',
             'Поля ручной проверки требуют явный статус review_status.')
    if not review_aware:
        statuses = [
            item['support_status']
            for group in ('elements', 'layers')
            for item in intent[group]
        ]
        statuses.append(intent['proportions']['support_status'])
        expected = (
            'needs_confirmation' if 'needs_confirmation' in statuses
            else 'partial' if 'planned' in statuses
            else 'ready'
        )
        if intent['status'] != expected:
            _add(issues, 'DESIGN_INTENT_STATUS_MISMATCH', '/garment_spec/design_intent/status',
                 'Статус конструктивного плана не соответствует состоянию его элементов.')
        if require_ready and expected != 'ready':
            _add(
                issues,
                'GARMENT_DESIGN_NOT_COMPILED',
                '/garment_spec/design_intent',
                'В фасоне есть неподтверждённые или ещё не реализованные детали. '
                'Их нельзя молча исключить из итоговой выкройки.',
            )
        return

    active: list[Mapping[str, Any]] = []
    for group in ('elements', 'layers'):
        for index, item in enumerate(intent[group]):
            pointer = f'/garment_spec/design_intent/{group}/{index}'
            included = item.get('included')
            if included is False:
                if item['support_status'] != 'excluded' or item['module_id'] is not None:
                    _add(issues, 'DESIGN_EXCLUSION_MISMATCH', pointer,
                         'Исключённая деталь должна иметь статус excluded без модуля.')
                continue
            if included is not True:
                _add(issues, 'DESIGN_REVIEW_FIELD_MISSING', f'{pointer}/included',
                     'Для проверки фасона явно укажите, включена ли деталь.')
            if item['support_status'] == 'excluded':
                _add(issues, 'DESIGN_EXCLUSION_MISMATCH', pointer,
                     'Включённая деталь не может иметь статус excluded.')
            dimensions = item.get('dimensions_mm') if group == 'elements' else None
            if (isinstance(dimensions, Mapping)
                    and any(value is not None for value in dimensions.values())
                    and item['support_status'] == 'supported'):
                _add(issues, 'DESIGN_DIMENSION_NOT_COMPILED', f'{pointer}/dimensions_mm',
                     'Ручной размер нельзя пометить поддержанным, пока модуль его не применяет.')
            active.append(item)

    included_main = [
        item for item in intent['layers']
        if item.get('included') is not False and item['role'] == 'main'
    ]
    if len(included_main) != 1:
        _add(issues, 'DESIGN_MAIN_LAYER_COUNT', '/garment_spec/design_intent/layers',
             'После проверки должен остаться ровно один основной слой изделия.')

    proportions = intent['proportions']
    if proportions['support_status'] == 'excluded':
        _add(issues, 'DESIGN_PROPORTIONS_EXCLUDED', '/garment_spec/design_intent/proportions',
             'Пропорции изделия нельзя исключить из проверки.')
    active.append(proportions)

    questions = intent['pending_questions']
    answers = intent.get('question_answers')
    if not isinstance(answers, list):
        answers = []
        _add(issues, 'DESIGN_ANSWERS_MISSING', '/garment_spec/design_intent/question_answers',
             'Для проверки фасона сохраните ответы на вопросы модели.')
    answer_questions = [item.get('question') for item in answers]
    if len(answer_questions) != len(set(answer_questions)):
        _add(issues, 'DESIGN_ANSWER_DUPLICATE', '/garment_spec/design_intent/question_answers',
             'На каждый вопрос модели должен быть один ответ.')
    if set(answer_questions) != set(questions):
        _add(issues, 'DESIGN_ANSWER_QUESTION_MISMATCH',
             '/garment_spec/design_intent/question_answers',
             'Список ответов должен точно соответствовать вопросам модели.')

    unanswered = any(not str(item.get('answer_ru', '')).strip() for item in answers)
    unconfirmed = any(item.get('confirmed_by_user') is not True for item in active)
    statuses = [item['support_status'] for item in active]
    expected = (
        'needs_confirmation' if unanswered or unconfirmed or 'needs_confirmation' in statuses
        else 'partial' if 'planned' in statuses
        else 'ready'
    )
    if intent['status'] != expected:
        _add(issues, 'DESIGN_INTENT_STATUS_MISMATCH', '/garment_spec/design_intent/status',
             'Статус конструктивного плана не соответствует состоянию его элементов.')
    review_status = intent.get('review_status')
    if review_status == 'confirmed' and (unanswered or unconfirmed):
        _add(issues, 'DESIGN_REVIEW_INCOMPLETE', '/garment_spec/design_intent/review_status',
             'Проверку нельзя подтвердить, пока не проверены детали и не даны ответы.')
    reviewed_at = intent.get('reviewed_at')
    if (review_status == 'confirmed') != (reviewed_at is not None):
        _add(issues, 'DESIGN_REVIEW_TIMESTAMP_MISMATCH',
             '/garment_spec/design_intent/reviewed_at',
             'Время проверки сохраняется только для подтверждённого плана.')
    if require_ready and review_status != 'confirmed':
        _add(
            issues,
            'DESIGN_REVIEW_NOT_CONFIRMED',
            '/garment_spec/design_intent/review_status',
            'Перед подтверждением фасона проверьте все детали, слои, пропорции и ответы.',
        )
    if require_ready and expected != 'ready':
        _add(
            issues,
            'GARMENT_DESIGN_NOT_COMPILED',
            '/garment_spec/design_intent',
            'В фасоне есть неподтверждённые или ещё не реализованные детали. '
            'Их нельзя молча исключить из итоговой выкройки.',
        )


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
    _validate_design_intent(spec, issues, require_ready=True)
    issues.extend(_measurement_issues(
        request['body_measurements'], spec['garment_type'], spec['parameters']['sleeve']['type'],
    ))

    method = request['pattern_method']
    expected_method = (
        ('kroika-light-jacket', '0.1.0')
        if spec['garment_type'] == 'jacket'
        else ('kroika-woven-trousers', '0.1.0')
        if spec['garment_type'] in {'trousers', 'shorts'}
        else ('kroika-gc-woven', '0.1.0')
    )
    if (method['id'], method['version']) != expected_method:
        _add(issues, 'METHOD_NOT_AVAILABLE', '/pattern_method',
             'Для выбранного изделия нужна отдельная доступная версия методики.')

    fabric = request['fabric_properties']
    if fabric['structure'] != 'woven' or fabric['stability'] != 'stable':
        _add(issues, 'FABRIC_OUTSIDE_METHOD', '/fabric_properties',
             'Текущая методика исследуется только для стабильной неэластичной ткани.')
    if max(fabric['stretch_percent'].values()) > 5:
        _add(issues, 'FABRIC_STRETCH_OUTSIDE_METHOD', '/fabric_properties/stretch_percent',
             'Растяжимость выше 5% не входит в область текущей методики.')

    parameters = spec['parameters']
    garment_type = spec['garment_type']
    jacket = parameters.get('jacket', {})
    expected_preset = {
        'dress': {
            'fitted': 'woven_fitted_trial',
            'semi_fitted': 'woven_semi_fitted_trial',
        }.get(parameters['bodice_fit']),
        'sundress': {
            'fitted': 'woven_fitted_trial',
            'semi_fitted': 'woven_semi_fitted_trial',
        }.get(parameters['bodice_fit']),
        'skirt': 'woven_skirt_trial',
        'top': 'woven_top_trial',
        'blouse': 'woven_blouse_trial',
        'shirt': 'woven_shirt_trial',
        'vest': 'woven_vest_trial',
        'jacket': 'woven_light_jacket_trial',
        'trousers': 'woven_straight_trousers_trial',
        'shorts': 'woven_tailored_shorts_trial',
    }.get(garment_type)
    finishing = parameters['finishing']
    common = (
        expected_preset is not None
        and request['fit_settings']['preset']['id'] == expected_preset
        and (
            garment_type in {'trousers', 'shorts'}
            or (
                parameters['neckline']['type'] == 'round'
                and parameters['skirt']['type'] == 'a_line'
            )
        )
    )
    supported_variant = common and any((
        garment_type in {'dress', 'sundress'}
        and parameters['sleeve']['type'] == 'sleeveless'
        and parameters['closure']['type'] == 'zipper'
        and parameters['closure']['location'] == 'center_back'
        and finishing['neckline_facing'] is True
        and finishing['armhole_facing'] is True
        and not finishing.get('waistband', False)
        and not finishing.get('front_placket', False)
        and not finishing.get('collar', False),
        garment_type == 'skirt'
        and parameters['sleeve']['type'] == 'sleeveless'
        and parameters['closure']['type'] == 'zipper'
        and parameters['closure']['location'] == 'center_back'
        and finishing.get('waistband') is True
        and finishing['neckline_facing'] is False
        and finishing['armhole_facing'] is False
        and not finishing.get('front_placket', False)
        and not finishing.get('collar', False),
        garment_type == 'top'
        and parameters['sleeve']['type'] == 'sleeveless'
        and parameters['closure']['type'] == 'zipper'
        and parameters['closure']['location'] == 'center_back'
        and finishing['neckline_facing'] is True
        and finishing['armhole_facing'] is True
        and not finishing.get('waistband', False)
        and not finishing.get('front_placket', False)
        and not finishing.get('collar', False),
        garment_type == 'blouse'
        and parameters['sleeve']['type'] == 'long'
        and parameters['closure']['type'] == 'zipper'
        and parameters['closure']['location'] == 'center_back'
        and finishing['neckline_facing'] is True
        and finishing['armhole_facing'] is False
        and not finishing.get('waistband', False)
        and not finishing.get('front_placket', False)
        and not finishing.get('collar', False),
        garment_type == 'shirt'
        and parameters['sleeve']['type'] == 'long'
        and parameters['closure']['type'] == 'buttons'
        and parameters['closure']['location'] == 'center_front'
        and finishing['neckline_facing'] is False
        and finishing['armhole_facing'] is False
        and not finishing.get('waistband', False)
        and finishing.get('front_placket') is True
        and finishing.get('collar') is True,
        garment_type == 'vest'
        and parameters['sleeve']['type'] == 'sleeveless'
        and parameters['closure']['type'] == 'buttons'
        and parameters['closure']['location'] == 'center_front'
        and finishing.get('front_placket') is True
        and finishing['neckline_facing'] is True
        and finishing['armhole_facing'] is True
        and not finishing.get('waistband', False)
        and not finishing.get('collar', False),
        garment_type == 'jacket'
        and method['id'] == 'kroika-light-jacket'
        and parameters['bodice_fit'] == 'semi_fitted'
        and parameters['shaping'] == 'princess_seams'
        and parameters['sleeve']['type'] == 'long'
        and parameters['closure']['type'] == 'buttons'
        and parameters['closure']['location'] == 'center_front'
        and jacket.get('variant') == 'light_single_breasted'
        and jacket.get('button_count') == 2
        and jacket.get('pocket_type') == 'patch'
        and jacket.get('sleeve_construction') == 'one_piece'
        and jacket.get('lining') == 'full'
        and request['fit_settings']['wearing_ease_mm']['bust'] >= 90 + jacket.get('underlayer_allowance_mm', 31)
        and request['fit_settings']['wearing_ease_mm']['waist'] >= 110 + jacket.get('underlayer_allowance_mm', 31)
        and request['fit_settings']['wearing_ease_mm']['hips'] >= 90 + jacket.get('underlayer_allowance_mm', 31)
        and request['fit_settings']['wearing_ease_mm']['upper_arm'] >= 70 + jacket.get('underlayer_allowance_mm', 31)
        and finishing.get('front_facing') is True
        and finishing.get('lining') is True
        and finishing.get('pockets') is True
        and finishing.get('vent') is True
        and finishing.get('collar') is True
        and not finishing.get('waistband', False)
        and not finishing.get('armhole_facing', False),
        garment_type in {'trousers', 'shorts'}
        and method['id'] == 'kroika-woven-trousers'
        and parameters['bodice_fit'] == 'semi_fitted'
        and parameters['shaping'] == 'darts'
        and parameters['sleeve']['type'] == 'sleeveless'
        and parameters['closure']['type'] == 'zipper'
        and parameters['closure']['location'] == 'center_front'
        and parameters.get('trousers', {}).get('variant') == (
            'straight_trousers' if garment_type == 'trousers' else 'tailored_shorts'
        )
        and parameters.get('trousers', {}).get('waist_position') == 'natural'
        and parameters.get('trousers', {}).get('leg_shape') == 'straight'
        and parameters.get('trousers', {}).get('pocket_type') == 'slash'
        and parameters.get('trousers', {}).get('pleat_count') == 0
        and finishing.get('waistband') is True
        and finishing.get('pockets') is True
        and finishing.get('fly_front') is True
        and finishing['neckline_facing'] is False
        and finishing['armhole_facing'] is False
        and not finishing.get('lining', False),
    ))
    if not supported_variant:
        _add(
            issues, 'GARMENT_VARIANT_NOT_IMPLEMENTED', '/garment_spec/parameters',
            'Выбранная комбинация деталей не входит в ограниченный каталог этапа 14. '
            'Выберите один из явно показанных вариантов без произвольной подмены компонентов.',
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
    _validate_design_intent(
        project['garment_spec'], issues,
        require_ready=project['garment_spec']['selection_status'] == 'confirmed',
    )
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
