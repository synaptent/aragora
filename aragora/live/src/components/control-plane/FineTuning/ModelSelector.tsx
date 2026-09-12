'use client';

import { useState, useMemo } from 'react';

export interface AvailableModel {
  id: string;
  name: string;
  provider: string;
  vertical: string;
  type: 'primary' | 'embedding' | 'small';
  size: string;
  description: string;
  huggingFaceId: string;
  downloads?: number;
  recommended?: boolean;
}

export interface ModelSelectorProps {
  selectedModel?: AvailableModel | null;
  onSelectModel: (model: AvailableModel) => void;
  showAllModels?: boolean;
  filterVertical?: string;
  className?: string;
}

const AVAILABLE_MODELS: AvailableModel[] = [
  // Software
  {
    id: 'codellama-34b',
    name: 'CodeLlama 34B Instruct',
    provider: 'Meta',
    vertical: 'software',
    type: 'primary',
    size: '34B',
    description: 'Large code-focused LLM for code generation and review',
    huggingFaceId: 'codellama/CodeLlama-34b-Instruct-hf',
    downloads: 150000,
    recommended: true,
  },
  {
    id: 'codellama-7b',
    name: 'CodeLlama 7B Instruct',
    provider: 'Meta',
    vertical: 'software',
    type: 'small',
    size: '7B',
    description: 'Efficient code model for faster inference',
    huggingFaceId: 'codellama/CodeLlama-7b-Instruct-hf',
    downloads: 280000,
  },
  {
    id: 'codebert',
    name: 'CodeBERT',
    provider: 'Microsoft',
    vertical: 'software',
    type: 'embedding',
    size: '125M',
    description: 'Code embeddings for semantic search',
    huggingFaceId: 'microsoft/codebert-base',
    downloads: 500000,
  },
  // Legal
  {
    id: 'legal-bert',
    name: 'Legal BERT',
    provider: 'NLP@AUEB',
    vertical: 'legal',
    type: 'primary',
    size: '110M',
    description: 'BERT fine-tuned on legal documents',
    huggingFaceId: 'nlpaueb/legal-bert-base-uncased',
    downloads: 120000,
    recommended: true,
  },
  {
    id: 'legal-roberta',
    name: 'Legal RoBERTa',
    provider: 'LexLMs',
    vertical: 'legal',
    type: 'embedding',
    size: '125M',
    description: 'RoBERTa for legal text embeddings',
    huggingFaceId: 'lexlms/legal-roberta-base',
    downloads: 45000,
  },
  // Healthcare
  {
    id: 'clinical-bert',
    name: 'ClinicalBERT',
    provider: 'Medical AI',
    vertical: 'healthcare',
    type: 'primary',
    size: '110M',
    description: 'BERT trained on clinical notes',
    huggingFaceId: 'medicalai/ClinicalBERT',
    downloads: 180000,
    recommended: true,
  },
  {
    id: 'pubmedbert',
    name: 'PubMedBERT',
    provider: 'Microsoft',
    vertical: 'healthcare',
    type: 'embedding',
    size: '110M',
    description: 'BERT for biomedical NLP',
    huggingFaceId: 'microsoft/BiomedNLP-PubMedBERT-base-uncased-abstract-fulltext',
    downloads: 250000,
  },
  // Accounting
  {
    id: 'finbert',
    name: 'FinBERT',
    provider: 'Prosus AI',
    vertical: 'accounting',
    type: 'primary',
    size: '110M',
    description: 'BERT for financial sentiment analysis',
    huggingFaceId: 'ProsusAI/finbert',
    downloads: 200000,
    recommended: true,
  },
  {
    id: 'finbert-tone',
    name: 'FinBERT Tone',
    provider: 'Yiyang HKU',
    vertical: 'accounting',
    type: 'embedding',
    size: '110M',
    description: 'Financial tone classification',
    huggingFaceId: 'yiyanghkust/finbert-tone',
    downloads: 80000,
  },
  // Research
  {
    id: 'scibert',
    name: 'SciBERT',
    provider: 'Allen AI',
    vertical: 'research',
    type: 'primary',
    size: '110M',
    description: 'BERT for scientific text',
    huggingFaceId: 'allenai/scibert_scivocab_uncased',
    downloads: 300000,
    recommended: true,
  },
  {
    id: 'specter',
    name: 'SPECTER',
    provider: 'Allen AI',
    vertical: 'research',
    type: 'embedding',
    size: '110M',
    description: 'Scientific paper embeddings',
    huggingFaceId: 'allenai/specter',
    downloads: 150000,
  },
];

const VERTICAL_ICONS: Record<string, string> = {
  software: '&#x1F4BB;',
  legal: '&#x2696;',
  healthcare: '&#x1F3E5;',
  accounting: '&#x1F4CA;',
  research: '&#x1F52C;',
};

export function ModelSelector({
  selectedModel,
  onSelectModel,
  showAllModels = false,
  filterVertical,
  className = '',
}: ModelSelectorProps) {
  const [verticalFilter, setVerticalFilter] = useState<string>(filterVertical || '');
  const [typeFilter, setTypeFilter] = useState<string>('');
  const [searchQuery, setSearchQuery] = useState('');

  const verticals = useMemo(() => {
    const verts = [...new Set(AVAILABLE_MODELS.map((m) => m.vertical))];
    return verts.map((v) => ({ id: v, name: v.charAt(0).toUpperCase() + v.slice(1) }));
  }, []);

  const filteredModels = useMemo(() => {
    let models = AVAILABLE_MODELS;

    if (verticalFilter) {
      models = models.filter((m) => m.vertical === verticalFilter);
    }

    if (typeFilter) {
      models = models.filter((m) => m.type === typeFilter);
    }

    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      models = models.filter(
        (m) =>
          m.name.toLowerCase().includes(query) ||
          m.description.toLowerCase().includes(query) ||
          m.huggingFaceId.toLowerCase().includes(query),
      );
    }

    // Sort by recommended first, then by downloads
    return models.sort((a, b) => {
      if (a.recommended && !b.recommended) return -1;
      if (!a.recommended && b.recommended) return 1;
      return (b.downloads || 0) - (a.downloads || 0);
    });
  }, [verticalFilter, typeFilter, searchQuery]);

  const formatDownloads = (downloads?: number) => {
    if (!downloads) return '';
    if (downloads >= 1000000) return `${(downloads / 1000000).toFixed(1)}M`;
    if (downloads >= 1000) return `${(downloads / 1000).toFixed(0)}K`;
    return downloads.toString();
  };

  return (
    <div className={className}>
      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-4">
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search models..."
          className="flex-1 min-w-[200px] px-3 py-2 text-sm bg-bg border border-border rounded font-theme-data focus:outline-none focus:border-[var(--accent)]"
        />
        <select
          value={verticalFilter}
          onChange={(e) => setVerticalFilter(e.target.value)}
          className="px-3 py-2 text-sm bg-bg border border-border rounded font-theme-data focus:outline-none focus:border-[var(--accent)]"
        >
          <option value="">All Verticals</option>
          {verticals.map((v) => (
            <option key={v.id} value={v.id}>
              {v.name}
            </option>
          ))}
        </select>
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className="px-3 py-2 text-sm bg-bg border border-border rounded font-theme-data focus:outline-none focus:border-[var(--accent)]"
        >
          <option value="">All Types</option>
          <option value="primary">Primary (Large)</option>
          <option value="small">Small (Fast)</option>
          <option value="embedding">Embedding</option>
        </select>
      </div>

      {/* Model Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {filteredModels.map((model) => (
          <div
            key={model.id}
            onClick={() => onSelectModel(model)}
            className={`
              p-4 bg-bg border-2 rounded-lg cursor-pointer transition-all
              ${
                selectedModel?.id === model.id
                  ? 'border-[var(--accent)] bg-[var(--accent)]/5'
                  : 'border-border hover:border-text-muted'
              }
            `}
          >
            <div className="flex items-start gap-3">
              <span
                className="text-2xl"
                dangerouslySetInnerHTML={{ __html: VERTICAL_ICONS[model.vertical] || '&#x1F4BB;' }}
              />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <h4 className="font-theme-data font-bold text-text truncate">{model.name}</h4>
                  {model.recommended && (
                    <span className="px-1.5 py-0.5 text-xs bg-[var(--accent)]/20 text-[var(--accent)] rounded">
                      REC
                    </span>
                  )}
                </div>
                <p className="text-xs text-text-muted mt-1 line-clamp-1">{model.description}</p>
                <div className="flex items-center gap-3 mt-2 text-xs">
                  <span className="font-theme-data text-text-muted">{model.size}</span>
                  <span
                    className={`px-1.5 py-0.5 rounded ${
                      model.type === 'primary'
                        ? 'bg-cyan-900/30 text-cyan-400'
                        : model.type === 'small'
                          ? 'bg-yellow-900/30 text-yellow-400'
                          : 'bg-purple-900/30 text-purple-400'
                    }`}
                  >
                    {model.type}
                  </span>
                  {model.downloads && (
                    <span className="text-text-muted">
                      &#x2B07; {formatDownloads(model.downloads)}
                    </span>
                  )}
                </div>
              </div>
            </div>
            {(showAllModels || selectedModel?.id === model.id) && (
              <div className="mt-3 pt-3 border-t border-border">
                <code className="text-xs font-theme-data text-[var(--acid-cyan)] break-all">
                  {model.huggingFaceId}
                </code>
              </div>
            )}
          </div>
        ))}
      </div>

      {filteredModels.length === 0 && (
        <div className="text-center py-8 text-text-muted">
          No models found matching your criteria
        </div>
      )}
    </div>
  );
}
