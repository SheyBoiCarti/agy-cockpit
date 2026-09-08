import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import 'highlight.js/styles/github-dark.css';

interface MarkdownViewProps {
  content: string;
}

export const MarkdownView: React.FC<MarkdownViewProps> = ({ content }) => {
  return (
    <div className="prose prose-invert prose-sm max-w-none break-words leading-relaxed select-text">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          a: ({ node, ...props }) => (
            <a
              {...props}
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-400 hover:text-blue-300 underline underline-offset-2"
            />
          ),
          code: ({ node, className, children, ...props }) => {
            const match = /language-(\w+)/.exec(className || '');
            const isInline = !match && !String(children).includes('\n');
            if (isInline) {
              return (
                <code
                  className="bg-neutral-800 text-neutral-200 px-1.5 py-0.5 rounded font-mono text-xs"
                  {...props}
                >
                  {children}
                </code>
              );
            }
            return (
              <div className="relative my-3 rounded-lg overflow-hidden border border-neutral-800 bg-neutral-900">
                {match && (
                  <div className="px-3 py-1 bg-neutral-800/80 border-b border-neutral-700/50 text-[11px] font-mono text-neutral-400 uppercase">
                    {match[1]}
                  </div>
                )}
                <pre className="p-3 overflow-x-auto text-xs font-mono text-neutral-100 bg-neutral-950">
                  <code className={className} {...props}>
                    {children}
                  </code>
                </pre>
              </div>
            );
          },
          table: ({ node, ...props }) => (
            <div className="overflow-x-auto my-3 border border-neutral-800 rounded-lg">
              <table className="min-w-full divide-y divide-neutral-800 text-xs" {...props} />
            </div>
          ),
          th: ({ node, ...props }) => (
            <th className="px-3 py-2 bg-neutral-900 text-left font-semibold text-neutral-200" {...props} />
          ),
          td: ({ node, ...props }) => (
            <td className="px-3 py-2 border-t border-neutral-800/50 text-neutral-300" {...props} />
          ),
          blockquote: ({ node, ...props }) => (
            <blockquote className="border-l-2 border-neutral-600 pl-3 my-2 text-neutral-400 italic" {...props} />
          ),
          ul: ({ node, ...props }) => <ul className="list-disc pl-5 my-2 space-y-1" {...props} />,
          ol: ({ node, ...props }) => <ol className="list-decimal pl-5 my-2 space-y-1" {...props} />,
          p: ({ node, ...props }) => <p className="my-2" {...props} />,
          h1: ({ node, ...props }) => <h1 className="text-xl font-bold my-3 text-neutral-100" {...props} />,
          h2: ({ node, ...props }) => <h2 className="text-lg font-semibold my-2.5 text-neutral-100" {...props} />,
          h3: ({ node, ...props }) => <h3 className="text-base font-medium my-2 text-neutral-200" {...props} />,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
};
