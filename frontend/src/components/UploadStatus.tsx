// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import Icon from "./Icon";

export default function UploadStatus({ filename }: { filename: string }) {
  return (
    <div className="notice" role="status" aria-live="polite">
      <Icon name="upload" size={17} />
      <span>
        Adding <strong>{filename}</strong>… Uploading and checking the source.
        Keep this app open until it is saved.
      </span>
    </div>
  );
}
