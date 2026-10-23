"use client";

import { useUi } from "../_state/ui";
import { Icon } from "../_ui/Icon";
import { Sheet } from "../_ui/Sheet";
import { GeneratorForm } from "./GeneratorForm";

export function GeneratorSheet() {
  const { sheet, closeSheet } = useUi();
  return (
    <Sheet open={sheet === "new"} onClose={closeSheet} labelledBy="gen-title" className="sheet-gen">
      <header className="sheet-head">
        <div>
          <p className="label">New</p>
          <h2 id="gen-title" className="sheet-title display">
            Build a program
          </h2>
        </div>
        <button type="button" className="btn btn-quiet btn-icon" aria-label="Close" onClick={closeSheet}>
          <Icon name="close" />
        </button>
      </header>
      <div className="sheet-scroll">
        <GeneratorForm />
      </div>
    </Sheet>
  );
}
