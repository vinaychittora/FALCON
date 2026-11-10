/** The colour code used on boxes and cards. */
export default function CertaintyLegend() {
  return (
    <p className="certainty-legend" aria-label="Colour code">
      <span className="certainty-likely">
        <i aria-hidden="true" /> Likely
      </span>
      <span className="certainty-probable">
        <i aria-hidden="true" /> Probable · look-alikes, often one genus
      </span>
      <span className="certainty-possible">
        <i aria-hidden="true" /> Possible · faint guess
      </span>
      <span className="certainty-unknown">
        <i aria-hidden="true" /> Unknown
      </span>
    </p>
  );
}
