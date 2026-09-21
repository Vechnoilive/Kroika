import type {FitSettings, GarmentSpec, GarmentType} from './types';

export const GARMENT_OPTIONS: Array<{id: GarmentType; name: string; short: string}> = [
  {id: 'dress', name: 'Платье', short: 'лиф + юбка'},
  {id: 'sundress', name: 'Сарафан', short: 'без рукавов'},
  {id: 'skirt', name: 'Юбка', short: 'А-силуэт + пояс'},
  {id: 'top', name: 'Топ', short: 'без рукавов'},
  {id: 'blouse', name: 'Блузка', short: 'длинный рукав'},
  {id: 'shirt', name: 'Рубашка', short: 'планка + воротник'},
  {id: 'vest', name: 'Жилет', short: 'планка + обтачки'},
  {id: 'jacket', name: 'Лёгкий жакет', short: 'лацкан + подкладка'},
];

export const GARMENT_NAMES: Record<GarmentType, string> = Object.fromEntries(
  GARMENT_OPTIONS.map((item) => [item.id, item.name]),
) as Record<GarmentType, string>;

const PRESETS: Record<GarmentType, string> = {
  dress: 'woven_semi_fitted_trial',
  sundress: 'woven_semi_fitted_trial',
  skirt: 'woven_skirt_trial',
  top: 'woven_top_trial',
  blouse: 'woven_blouse_trial',
  shirt: 'woven_shirt_trial',
  vest: 'woven_vest_trial',
  jacket: 'woven_light_jacket_trial',
};

const EASE: Record<GarmentType, FitSettings['wearing_ease_mm']> = {
  dress: {bust: 60, waist: 40, hips: 60, upper_arm: 50},
  sundress: {bust: 60, waist: 40, hips: 60, upper_arm: 50},
  skirt: {bust: 0, waist: 20, hips: 40, upper_arm: 0},
  top: {bust: 50, waist: 40, hips: 50, upper_arm: 0},
  blouse: {bust: 80, waist: 80, hips: 80, upper_arm: 60},
  shirt: {bust: 100, waist: 100, hips: 100, upper_arm: 70},
  vest: {bust: 60, waist: 50, hips: 60, upper_arm: 0},
  jacket: {bust: 110, waist: 130, hips: 110, upper_arm: 90},
};

export function methodForGarment(type: GarmentType) {
  return type === 'jacket' ? 'kroika-light-jacket' : 'kroika-gc-woven';
}

export function presetForGarment(type: GarmentType, fit: GarmentSpec['parameters']['bodice_fit']) {
  if (type === 'dress' || type === 'sundress') {
    return fit === 'fitted' ? 'woven_fitted_trial' : 'woven_semi_fitted_trial';
  }
  return PRESETS[type];
}

export function easeForGarment(type: GarmentType, underlayerAllowanceMm = 10): FitSettings['wearing_ease_mm'] {
  const values = {...EASE[type]};
  if (type === 'jacket') {
    const delta = underlayerAllowanceMm - 10;
    return {
      bust: values.bust + delta,
      waist: values.waist + delta,
      hips: values.hips + delta,
      upper_arm: values.upper_arm + delta,
    };
  }
  return values;
}

export function configureGarment(spec: GarmentSpec, type: GarmentType): GarmentSpec {
  const sleeved = type === 'blouse' || type === 'shirt' || type === 'jacket';
  const frontOpening = type === 'shirt' || type === 'vest' || type === 'jacket';
  const separateSkirt = type === 'skirt';
  const dressLike = type === 'dress' || type === 'sundress';
  return {
    ...spec,
    garment_type: type,
    selection_status: 'proposed',
    confirmed_at: null,
    parameters: {
      ...spec.parameters,
      bodice_fit: type === 'shirt' || type === 'blouse' || type === 'jacket' ? 'semi_fitted' : spec.parameters.bodice_fit,
      shaping: type === 'jacket' ? 'princess_seams' : 'darts',
      neckline: {...spec.parameters.neckline, type: 'round'},
      sleeve: {type: sleeved ? 'long' : 'sleeveless', length_mm: sleeved ? 580 : null},
      skirt: {...spec.parameters.skirt, type: 'a_line'},
      upper: {length_below_waist_mm: type === 'jacket' ? 240 : dressLike || separateSkirt ? 100 : type === 'top' ? 80 : 120},
      jacket: type === 'jacket' ? {
        variant: 'light_single_breasted',
        front_extension_mm: 35,
        lapel_width_mm: 70,
        roll_line_from_waist_mm: 180,
        collar_stand_mm: 25,
        collar_fall_mm: 55,
        underlayer_allowance_mm: 10,
        vent_length_mm: 180,
        pocket_width_mm: 160,
        pocket_depth_mm: 180,
        button_count: 2,
        pocket_type: 'patch',
        sleeve_construction: 'one_piece',
        lining: 'full',
      } : undefined,
      closure: frontOpening
        ? {type: 'buttons', location: 'center_front', length_mm: 550}
        : {type: 'zipper', location: 'center_back', length_mm: 550},
      finishing: {
        neckline_facing: !separateSkirt && (type === 'blouse' || !sleeved),
        armhole_facing: !separateSkirt && !sleeved,
        waistband: separateSkirt,
        front_placket: frontOpening,
        collar: type === 'shirt' || type === 'jacket',
        front_facing: type === 'jacket',
        lining: type === 'jacket',
        pockets: type === 'jacket',
        vent: type === 'jacket',
      },
    },
  };
}
