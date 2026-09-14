from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

from jsonschema import Draft202012Validator
from openapi_spec_validator import validate
from openapi_spec_validator.readers import read_from_filename

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from kroika_contracts.contract_io import (  # noqa: E402
    ContractValidationError, available_schemas, load_schema, validate_document,
)
from kroika_contracts.hashing import compute_input_hash  # noqa: E402
from kroika_contracts.migrations import (  # noqa: E402
    MigrationRegistry, MigrationStep, UnsupportedProjectVersion, migrate_project,
)
from kroika_contracts.ports import AIProvider, PatternEngine  # noqa: E402
from kroika_contracts.semantic import (  # noqa: E402
    SemanticContractError, validate_ai_analysis, validate_engine_request, validate_project,
    validate_validation_report,
)


def example(name: str):
    return json.loads((ROOT / 'examples' / 'v1' / name).read_text(encoding='utf-8'))


class JsonSchemaContracts(unittest.TestCase):
    def test_every_schema_is_valid_draft_2020_12(self):
        names = available_schemas()
        self.assertEqual(len(names), 13)
        for name in names:
            with self.subTest(schema=name):
                Draft202012Validator.check_schema(load_schema(name))

    def test_examples_and_all_stage2_formulas_match_contracts(self):
        validate_document('pattern-project', example('example-dress-project.json'))
        validate_document('pattern-engine-request', example('example-engine-request.json'))
        validate_document('pattern-engine-result', example('example-engine-result.json'))
        validate_document('validation-report', example('example-validation-report.json'))
        validate_document('ai-analysis-request', example('example-ai-request.json'))
        validate_document('ai-style-analysis', example('example-ai-response.json'))
        registry = json.loads(
            (ROOT / 'references/stage2/formula-registry.json').read_text(encoding='utf-8'))
        self.assertEqual(len(registry['records']), 41)
        for record in registry['records']:
            with self.subTest(formula=record['formula_id']):
                validate_document('formula-record', record)

    def test_ready_measurements_never_infer_a_missing_value(self):
        project = example('example-dress-project.json')
        del project['body_measurements']['values']['bust']
        with self.assertRaises(ContractValidationError):
            validate_document('body-measurements', project['body_measurements'])

    def test_millimetres_are_mandatory_inside_contract(self):
        project = example('example-dress-project.json')
        project['body_measurements']['values']['bust']['unit'] = 'cm'
        with self.assertRaises(ContractValidationError):
            validate_document('body-measurements', project['body_measurements'])

    def test_extra_and_nonfinite_values_are_rejected(self):
        project = example('example-dress-project.json')
        project['body_measurements']['secret_average'] = 900
        with self.assertRaises(ContractValidationError):
            validate_document('body-measurements', project['body_measurements'])
        project = example('example-dress-project.json')
        project['body_measurements']['values']['bust']['value'] = float('nan')
        with self.assertRaises(ContractValidationError):
            validate_document('body-measurements', project['body_measurements'])

    def test_ai_request_cannot_contain_measurements(self):
        request = example('example-ai-request.json')
        request['body_measurements'] = {'bust': 920}
        with self.assertRaises(ContractValidationError):
            validate_document('ai-analysis-request', request)

    def test_confirmed_spec_cannot_keep_unsupported_features(self):
        spec = example('example-dress-project.json')['garment_spec']
        spec['unsupported_features'] = ['corset']
        with self.assertRaises(ContractValidationError):
            validate_document('garment-spec', spec)

    def test_production_export_requires_toile_verified(self):
        report = _report_fixture()
        report['status'] = 'passed'
        report['issues'] = []
        report['checks'][0]['status'] = 'passed'
        report['production_export_allowed'] = True
        with self.assertRaises(ContractValidationError):
            validate_document('validation-report', report)

    def test_openapi_31_and_external_references_are_valid(self):
        spec, base_uri = read_from_filename(str(ROOT / 'schemas' / 'openapi.v1.yaml'))
        validate(spec, base_uri=base_uri)
        operation_ids = []
        for path_item in spec['paths'].values():
            for method, operation in path_item.items():
                if method in {'get', 'post', 'put', 'patch', 'delete'}:
                    operation_ids.append(operation['operationId'])
        self.assertEqual(len(operation_ids), len(set(operation_ids)))
        self.assertEqual(len(operation_ids), 9)


class SemanticContracts(unittest.TestCase):
    def setUp(self):
        self.request = example('example-engine-request.json')
        self.request['input_hash'] = compute_input_hash(self.request)

    def test_valid_engine_request_and_hash(self):
        validate_engine_request(self.request)

    def test_ai_response_has_no_sleeve_contradiction(self):
        response = example('example-ai-response.json')
        validate_ai_analysis(response)
        response['sleeves']['present'] = True
        with self.assertRaises(SemanticContractError) as caught:
            validate_ai_analysis(response)
        self.assertIn('AI_SLEEVE_CONTRADICTION',
                      {item.code for item in caught.exception.issues})

    def test_hash_ignores_ids_labels_timestamps_and_provenance(self):
        original = compute_input_hash(self.request)
        changed = deepcopy(self.request)
        changed['request_id'] = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
        changed['project_id'] = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
        changed['body_measurements']['name'] = 'Другое имя'
        changed['body_measurements']['values']['bust']['source'] = 'preset'
        changed['garment_spec']['confirmed_at'] = '2026-09-14T13:00:00Z'
        self.assertEqual(compute_input_hash(changed), original)
        changed['body_measurements']['values']['bust']['value'] += 1
        self.assertNotEqual(compute_input_hash(changed), original)

    def test_hash_mismatch_is_a_clear_semantic_error(self):
        self.request['input_hash'] = '0' * 64
        with self.assertRaises(SemanticContractError) as caught:
            validate_engine_request(self.request)
        self.assertIn('INPUT_HASH_MISMATCH', {item.code for item in caught.exception.issues})

    def test_original_centimetres_must_match_normalized_millimetres(self):
        self.request['body_measurements']['values']['bust']['original_input']['value'] = 91
        self.request['input_hash'] = compute_input_hash(self.request)
        with self.assertRaises(SemanticContractError) as caught:
            validate_engine_request(self.request)
        self.assertIn('NORMALIZATION_MISMATCH',
                      {item.code for item in caught.exception.issues})

    def test_ease_shares_and_measurement_arcs_are_relationally_checked(self):
        self.request['fit_settings']['distribution'] = {'front_share': 0.8, 'back_share': 0.8}
        self.request['body_measurements']['values']['back_bust_arc']['value'] = 1000
        self.request['input_hash'] = compute_input_hash(self.request)
        with self.assertRaises(SemanticContractError) as caught:
            validate_engine_request(self.request)
        codes = {item.code for item in caught.exception.issues}
        self.assertEqual(codes, {'EASE_DISTRIBUTION_SUM', 'MEASUREMENT_ARC_NOT_SMALLER'})

    def test_method_fabric_and_variant_boundaries_fail_closed(self):
        self.request['pattern_method']['version'] = '0.2.0'
        self.request['fabric_properties']['structure'] = 'knit'
        self.request['garment_spec']['parameters']['sleeve'] = {'type': 'long', 'length_mm': 600}
        self.request['input_hash'] = compute_input_hash(self.request)
        with self.assertRaises(SemanticContractError) as caught:
            validate_engine_request(self.request)
        codes = {item.code for item in caught.exception.issues}
        self.assertTrue({'METHOD_NOT_AVAILABLE', 'FABRIC_OUTSIDE_METHOD',
                         'GARMENT_VARIANT_NOT_IMPLEMENTED'} <= codes)

    def test_validation_report_cannot_hide_a_blocker(self):
        report = _report_fixture()
        report['status'] = 'warnings'
        with self.assertRaises(SemanticContractError) as caught:
            validate_validation_report(report)
        self.assertIn('REPORT_BLOCKER_STATUS', {item.code for item in caught.exception.issues})

    def test_validation_report_cannot_hide_a_failed_check(self):
        report = _report_fixture()
        report['issues'] = []
        report['status'] = 'passed'
        with self.assertRaises(SemanticContractError) as caught:
            validate_validation_report(report)
        self.assertIn('REPORT_FAILED_CHECK_STATUS',
                      {item.code for item in caught.exception.issues})

    def test_current_draft_project_is_valid_but_not_production_ready(self):
        project = example('example-dress-project.json')
        validate_project(project)
        project['status'] = 'ready_for_production_export'
        with self.assertRaises(ContractValidationError):
            validate_project(project)

    def test_project_rejects_inconsistent_original_units_before_generation(self):
        project = example('example-dress-project.json')
        project['body_measurements']['values']['waist']['original_input']['value'] = 75
        with self.assertRaises(SemanticContractError) as caught:
            validate_project(project)
        self.assertIn('NORMALIZATION_MISMATCH',
                      {item.code for item in caught.exception.issues})

    def test_generated_result_report_and_history_must_refer_to_each_other(self):
        project = example('example-dress-project.json')
        result = example('example-engine-result.json')
        project['status'] = 'validation_failed'
        project['latest_generation'] = result
        project['generation_history'] = [{
            'generation_id': result['generation_id'],
            'input_hash': result['input_hash'],
            'engine_version': result['engine_version'],
            'method_version': result['pattern_method']['version'],
            'created_at': result['created_at'],
            'status': result['status'],
        }]
        validate_project(project)
        project['latest_generation']['validation_report']['generation_id'] = (
            'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')
        with self.assertRaises(SemanticContractError) as caught:
            validate_project(project)
        self.assertIn('GENERATION_REPORT_ID_MISMATCH',
                      {item.code for item in caught.exception.issues})


class MigrationAndPortContracts(unittest.TestCase):
    def test_current_project_migration_is_a_deep_copy(self):
        original = example('example-dress-project.json')
        migrated = migrate_project(original)
        self.assertEqual(migrated, original)
        self.assertIsNot(migrated, original)
        migrated['name'] = 'Изменено'
        self.assertNotEqual(migrated['name'], original['name'])

    def test_missing_and_unknown_versions_are_never_guessed(self):
        with self.assertRaises(UnsupportedProjectVersion):
            migrate_project({'project_id': 'legacy'})
        with self.assertRaises(UnsupportedProjectVersion):
            migrate_project({'schema_version': '0.9.0'})

    def test_registry_applies_ordered_copy_on_write_steps(self):
        def to_two(project):
            project['schema_version'] = '2.0.0'
            project['history'] = ['1→2']
            return project

        def to_three(project):
            project['schema_version'] = '3.0.0'
            project['history'].append('2→3')
            return project

        registry = MigrationRegistry('3.0.0', {
            '1.0.0': MigrationStep('2.0.0', to_two),
            '2.0.0': MigrationStep('3.0.0', to_three),
        })
        source = {'schema_version': '1.0.0'}
        self.assertEqual(registry.migrate(source),
                         {'schema_version': '3.0.0', 'history': ['1→2', '2→3']})
        self.assertEqual(source, {'schema_version': '1.0.0'})

    def test_ai_and_engine_ports_are_separate_structural_interfaces(self):
        class FakeAI:
            provider_id = 'mock'

            async def analyze_style(self, request):
                return example('example-ai-response.json')

        class FakeEngine:
            engine_id = 'mock-engine'
            engine_version = '0.0.0'

            def generate(self, request):
                return {'status': 'rejected'}

        self.assertIsInstance(FakeAI(), AIProvider)
        self.assertIsInstance(FakeEngine(), PatternEngine)
        response = asyncio.run(FakeAI().analyze_style(example('example-ai-request.json')))
        validate_document('ai-style-analysis', response)


def _report_fixture():
    return {
        'schema_version': '1.0.0',
        'report_id': '88888888-8888-4888-8888-888888888888',
        'project_id': '11111111-1111-4111-8111-111111111111',
        'generation_id': '99999999-9999-4999-8999-999999999999',
        'input_hash': '1' * 64,
        'validator_version': '0.1.0',
        'created_at': '2026-09-14T12:00:00Z',
        'status': 'failed',
        'method_validation_status': 'experimental',
        'issues': [{
            'code': 'SEAM_LENGTH_MISMATCH', 'severity': 'blocking_error',
            'message_ru': 'Длины боковых швов не совпадают.',
            'json_pointer': '/pattern/pieces/0', 'piece_id': 'skirt_front',
            'formula_id': None, 'measured_value': 10.066,
            'limit_value': 1.0, 'unit': 'mm',
        }],
        'checks': [{
            'id': 'seams.side', 'status': 'failed',
            'message_ru': 'Остаток превышает допуск.',
            'measured_value': 10.066, 'limit_value': 1.0, 'unit': 'mm',
        }],
        'diagnostic_export_allowed': True,
        'production_export_allowed': False,
    }
