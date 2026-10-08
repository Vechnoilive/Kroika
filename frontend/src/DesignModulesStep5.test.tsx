import {useState} from 'react';
import {render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {describe, expect, it, vi} from 'vitest';
import {DesignIntentEditor} from './DesignIntentEditor';
import {buildDesignIntent, finalizeDesignIntent} from './designIntent';
import {COMBINATION_CAPABILITIES, compositionOrder, structuralConflicts} from './designModules';
import {canonicalGenerationPayload, stableJson} from './generation';
import {makeDemoProject} from './demoProject';
import type {GarmentDesignIntent, GarmentSpec, StyleAnalysis} from './types';

const analysis: StyleAnalysis = {
  status:'ok',garment_category:'dress',silhouette:{fit:'semi_fitted',confidence:1},
  neckline:{front:'round',confidence:1},sleeves:{present:false,length:'sleeveless',confidence:1},
  lower_part:{type:'a_line',length_category:'midi',confidence:1},uncertainties:[],targeted_questions:[],
  design_features:{elements:[],layers:[{layer_id:'fabric',role:'main',coverage:'full',material_hint_ru:'Ткань',opacity:'opaque',drape:'medium',confidence:1,requires_confirmation:false}],
    proportions:{waist_position:'natural',volume:'regular',hem_shape:'straight',asymmetry:'no',confidence:1}},
};
function fixture() {
  const project=makeDemoProject('Сочетания');
  const intent=buildDesignIntent(analysis,project.garment_spec)!;
  intent.layers[0].confirmed_by_user=true;intent.proportions.confirmed_by_user=true;
  const base={description_ru:'Отделка',confidence:1,evidence_ru:'Фото',requires_confirmation:false,included:true,confirmed_by_user:true,
    support_status:'supported' as const,construction:'separate_piece' as const,location:'hem' as const,count:1,symmetry:'symmetric' as const};
  intent.elements=[{...base,source_element_id:'ruffle',type:'ruffle',variant:'gathered',module_id:'tiered_hem_ruffle_v2',selected_module_id:'tiered_hem_ruffle_v2',dimensions_mm:{depth:80,width:60,length:null,spacing:null}},
    {...base,source_element_id:'flounce',type:'flounce',variant:'circular',module_id:'tiered_hem_flounce_v2',selected_module_id:'tiered_hem_flounce_v2',dimensions_mm:{depth:80,width:null,length:null,spacing:null}}];
  project.garment_spec.design_intent=intent;
  return {project,intent};
}
function Harness({spec,initial}: {spec:GarmentSpec;initial:GarmentDesignIntent}) {
  const [intent,setIntent]=useState(initial);
  return <DesignIntentEditor spec={spec} intent={intent} analysis={analysis} busy={false} onChange={setIntent} onSave={vi.fn(async()=>{})}/>;
}

describe('composition and complete pattern stage 5',()=>{
  it('compiles unlike single tiers and includes their sequence in the cache key',()=>{
    const {project,intent}=fixture();
    expect(finalizeDesignIntent(intent,project.garment_spec,analysis).status).toBe('ready');
    expect(COMBINATION_CAPABILITIES).toBeDefined();
    const first=stableJson(canonicalGenerationPayload(project));
    expect(canonicalGenerationPayload(project).hash_contract_version).toBe('1.11.0');
    intent.elements.reverse();
    expect(stableJson(canonicalGenerationPayload(project))).not.toBe(first);
    expect(compositionOrder(project.garment_spec)[0][0]).toBe('flounce');
  });
  it('exposes the same partition and attachment capabilities and preserves real conflicts',()=>{
    const {project,intent}=fixture();
    expect(COMBINATION_CAPABILITIES.attachment_modules).toContain('diagonal_bodice_drape_v2');
    expect(COMBINATION_CAPABILITIES.partition_modules).toContain('offset_skirt_panel_v3');
    expect(structuralConflicts(project.garment_spec)).toEqual([]);
    intent.elements=[{...intent.elements[0],type:'hood',module_id:'fitted_two_piece_hood_v3'},
      {...intent.elements[0],type:'collar',module_id:'shaped_flat_collar_v3'}];
    expect(structuralConflicts(project.garment_spec)[0]).toContain('альтернативные');
  });
  it('lets the user reorder trims without dropping either element',async()=>{
    const {project,intent}=fixture();
    render(<Harness spec={project.garment_spec} initial={intent}/>);
    await userEvent.click(screen.getByRole('button',{name:'Опустить деталь 1'}));
    expect(screen.getByLabelText('Выбрать конструкцию детали 1')).toHaveValue('tiered_hem_flounce_v2');
    expect(screen.getByLabelText('Выбрать конструкцию детали 2')).toHaveValue('tiered_hem_ruffle_v2');
    expect(screen.getByRole('button',{name:'Поднять деталь 1'})).toBeDisabled();
  });
});
