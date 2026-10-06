import type {GarmentDesignIntent, GarmentSpec} from './types';

export const BACK_GARMENTS = ['dress', 'sundress', 'top', 'blouse'];
export const isBackQuestion = (question: string) => /спин|задн/i.test(question)
  && /конструк|вырез|горловин|шов|молни|заст[её]ж|шнур|ленточ|оформ/i.test(question)
  && !/сперед|передн|гульфик/i.test(question);

export function backAnswer(spec: GarmentSpec): string {
  const closure = spec.parameters.closure;
  const names = {zipper: 'Молния', buttons: 'Пуговицы с навесными петлями', lacing: 'Шнуровка лентой', none: 'Без застёжки сзади'};
  return `${names[closure.type]}: ${closure.location === 'center_back' ? 'центр спинки' : 'спинка без застёжки'}. Глубина горловины сзади ${spec.parameters.neckline.back_depth_mm / 10} см.${closure.location === 'center_back' ? ` Длина разреза ${Number(closure.length_mm) / 10} см.` : ''}`;
}

export function answerBackQuestions(intent: GarmentDesignIntent, spec: GarmentSpec): GarmentDesignIntent {
  const answers = new Map((intent.question_answers ?? []).map((item) => [item.question, item.answer_ru]));
  return {...intent, question_answers: intent.pending_questions.map((question) => ({
    question, answer_ru: isBackQuestion(question) ? backAnswer(spec) : answers.get(question) ?? '',
  }))};
}
