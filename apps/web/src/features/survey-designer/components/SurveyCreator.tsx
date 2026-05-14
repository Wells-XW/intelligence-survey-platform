import { useEffect, useRef, useCallback } from 'react';
import type { ICreatorOptions } from 'survey-creator-core';

// SurveyJS Creator is loaded dynamically to handle its internal React dependency
// We import CSS directly and use lazy loading for the JS bundle
import 'survey-core/survey-core.css';
import 'survey-creator-core/survey-creator-core.css';

interface SurveyCreatorProps {
  surveyJson: Record<string, unknown>;
  onJsonChange: (json: Record<string, unknown>) => void;
}

/**
 * Wraps SurveyJS Survey Creator (drag-and-drop questionnaire designer).
 * Uses dynamic import to handle SurveyJS's React dependency correctly.
 */
export function SurveyCreator({ surveyJson, onJsonChange }: SurveyCreatorProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const creatorRef = useRef<unknown>(null);

  const initCreator = useCallback(async () => {
    if (!containerRef.current) return;

    // Dynamic import to avoid SSR issues and handle React dependency
    const [
      { SurveyCreator: SurveyCreatorClass },
      { SurveyCreatorComponent },
    ] = await Promise.all([
      import('survey-creator-core'),
      import('survey-creator-react'),
    ]);

    // Clean up previous instance
    if (creatorRef.current) {
      const prev = creatorRef.current as { dispose?: () => void };
      prev.dispose?.();
    }

    const options = {
      showLogicTab: true,
      showTranslationTab: false,
      showPreviewBeforeAutoSave: false,
      showSurveyTitle: false,
      // Academic-friendly defaults
      questionTypes: [
        'text',
        'comment',
        'radiogroup',
        'checkbox',
        'dropdown',
        'rating',
        'ranking',
        'matrix',
        'matrixdropdown',
        'matrixdynamic',
        'multipletext',
        'boolean',
        'imagepicker',
        'html',
        'expression',
        'paneldynamic',
      ],
      // Custom localization for Chinese academic context
    };

    const creator = new SurveyCreatorClass(options);

    // Set initial JSON
    if (surveyJson && Object.keys(surveyJson).length > 0) {
      creator.JSON = surveyJson;
    } else {
      creator.JSON = { pages: [{ elements: [] }] };
    }

    // Listen for changes
    creator.onModified.add(() => {
      try {
        const json = creator.JSON;
        if (json) {
          onJsonChange(json);
        }
      } catch {
        // Ignore parse errors during editing
      }
    });

    creatorRef.current = creator;

    // Render the creator component
    const { createRoot } = await import('react-dom/client');
    const root = createRoot(containerRef.current);
    root.render(<SurveyCreatorComponent creator={creator} />);

    return () => {
      root.unmount();
    };
  }, []); // Only init once

  // Update JSON when it changes externally (e.g., after save/load)
  useEffect(() => {
    if (creatorRef.current) {
      const creator = creatorRef.current as { JSON: Record<string, unknown> };
      const currentJson = JSON.stringify(creator.JSON);
      const newJson = JSON.stringify(surveyJson);
      if (currentJson !== newJson) {
        creator.JSON = surveyJson;
      }
    } else {
      initCreator();
    }
  }, [surveyJson, initCreator]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (creatorRef.current) {
        const creator = creatorRef.current as { dispose?: () => void };
        creator.dispose?.();
        creatorRef.current = null;
      }
    };
  }, []);

  return (
    <div
      ref={containerRef}
      className="h-full w-full"
      style={{ minHeight: '600px' }}
    />
  );
}
