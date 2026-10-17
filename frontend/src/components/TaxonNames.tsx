import { createContext, useContext } from "react";
import { indexTaxonNames } from "../api/names";

export const TaxonNamesContext = createContext(indexTaxonNames([]));
export const useTaxonNames = () => useContext(TaxonNamesContext);
