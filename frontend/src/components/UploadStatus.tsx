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
