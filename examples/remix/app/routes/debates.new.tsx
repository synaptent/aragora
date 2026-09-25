import type { ActionFunctionArgs, MetaFunction } from '@remix-run/node';
import { json, redirect } from '@remix-run/node';
import { Form, useActionData, useNavigation } from '@remix-run/react';
import { getClient } from '../aragora.server';

export const meta: MetaFunction = () => [{ title: 'New Debate | Aragora' }];

export async function action({ request }: ActionFunctionArgs) {
  const formData = await request.formData();
  const task = formData.get('task') as string;
  const agents = formData.getAll('agents') as string[];
  const rounds = parseInt(formData.get('rounds') as string) || 5;

  if (!task?.trim()) {
    return json({ error: 'Please enter a debate topic' }, { status: 400 });
  }

  if (agents.length < 2) {
    return json({ error: 'Please select at least 2 agents' }, { status: 400 });
  }

  try {
    const client = getClient();
    const result = await client.debates.create({
      task: task.trim(),
      agents,
      rounds,
    });

    return redirect(`/debates/${result.debate_id}`);
  } catch (error) {
    return json({ error: 'Failed to create debate' }, { status: 500 });
  }
}

const AGENTS = [
  { id: 'claude', name: 'Claude', provider: 'Anthropic' },
  { id: 'gpt-4', name: 'GPT-4', provider: 'OpenAI' },
  { id: 'gemini', name: 'Gemini', provider: 'Google' },
  { id: 'grok', name: 'Grok', provider: 'xAI' },
  { id: 'mistral', name: 'Mistral Large', provider: 'Mistral' },
];

export default function NewDebate() {
  const actionData = useActionData<typeof action>();
  const navigation = useNavigation();
  const isSubmitting = navigation.state === 'submitting';

  return (
    <div style={{ maxWidth: '600px' }}>
      <h1 style={{ marginBottom: '2rem' }}>Create New Debate</h1>

      <Form method="post">
        <div style={{ marginBottom: '1.5rem' }}>
          <label htmlFor="task" style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 500 }}>
            Debate Topic
          </label>
          <textarea
            id="task"
            name="task"
            className="input"
            placeholder="What question should the agents debate?"
            rows={4}
            style={{ resize: 'vertical' }}
          />
        </div>

        <fieldset style={{ marginBottom: '1.5rem', border: 0 }}>
          <legend style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 500 }}>
            Select Agents
          </legend>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
            {AGENTS.map((agent) => (
              <label
                key={agent.id}
                style={{
                  padding: '0.5rem 1rem',
                  border: '1px solid var(--border)',
                  borderRadius: '0.5rem',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                }}
              >
                <input
                  type="checkbox"
                  name="agents"
                  value={agent.id}
                  defaultChecked={['claude', 'gpt-4', 'gemini'].includes(agent.id)}
                />
                {agent.name}
                <span style={{ fontSize: '0.75rem', opacity: 0.7 }}>
                  ({agent.provider})
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        <div style={{ marginBottom: '1.5rem' }}>
          <label htmlFor="rounds" style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 500 }}>
            Number of Rounds
          </label>
          <select id="rounds" name="rounds" className="input" defaultValue="5">
            <option value="3">3 rounds (Quick)</option>
            <option value="5">5 rounds (Standard)</option>
            <option value="7">7 rounds (Thorough)</option>
            <option value="9">9 rounds (Comprehensive)</option>
          </select>
        </div>

        {actionData?.error && (
          <div style={{ padding: '1rem', background: '#fee2e2', color: '#991b1b', borderRadius: '0.5rem', marginBottom: '1rem' }}>
            {actionData.error}
          </div>
        )}

        <button type="submit" className="button" disabled={isSubmitting} style={{ width: '100%' }}>
          {isSubmitting ? 'Creating...' : 'Start Debate'}
        </button>
      </Form>
    </div>
  );
}
