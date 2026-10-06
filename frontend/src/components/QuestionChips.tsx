import { ChevronIcon } from "./Icons";
import { SAMPLE_CARDS, SAMPLE_QUESTIONS } from "./sampleQuestions";

interface Props {
  onPick: (question: string) => void;
  disabled?: boolean;
  label?: string;
  variant?: "chips" | "cards";
}

export function QuestionChips({ onPick, disabled, label = "Sample questions", variant = "chips" }: Props) {
  if (variant === "cards") {
    return (
      <div className="sample-cards" role="group" aria-label={label}>
        {SAMPLE_CARDS.map(({ kind, question }) => (
          <button key={question} type="button" className="sample-card" disabled={disabled} onClick={() => onPick(question)}>
            <span className="sample-card__kind">{kind}</span>
            <span className="sample-card__question">{question}</span>
            <ChevronIcon className="sample-card__arrow" />
          </button>
        ))}
      </div>
    );
  }
  return (
    <div className="chips" role="group" aria-label={label}>
      {SAMPLE_QUESTIONS.map((q) => (
        <button key={q} type="button" className="chip" disabled={disabled} onClick={() => onPick(q)}>
          {q}
        </button>
      ))}
    </div>
  );
}
