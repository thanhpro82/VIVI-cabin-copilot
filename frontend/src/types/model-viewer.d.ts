import type { DetailedHTMLProps, HTMLAttributes } from "react";

type ModelViewerAttributes = DetailedHTMLProps<HTMLAttributes<HTMLElement>, HTMLElement> & {
  src?: string;
  alt?: string;
  "camera-controls"?: boolean;
  "disable-zoom"?: boolean;
  "camera-orbit"?: string;
  "field-of-view"?: string;
  "shadow-intensity"?: string | number;
  "shadow-softness"?: string | number;
  exposure?: string | number;
  "interaction-prompt"?: string;
};

// React 19 resolve custom JSX intrinsics qua React.JSX (không phải global JSX
// namespace cũ) — phải augment đúng "react" module thì `next build` (tsc)
// mới nhận diện được thẻ <model-viewer>.
declare module "react" {
  namespace JSX {
    interface IntrinsicElements {
      "model-viewer": ModelViewerAttributes;
    }
  }
}

export {};
