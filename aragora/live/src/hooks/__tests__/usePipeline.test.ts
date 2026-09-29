import { act, renderHook } from '@testing-library/react';

import { usePipeline } from '../usePipeline';
import { useApi } from '../useApi';

jest.mock('../useApi', () => ({ useApi: jest.fn() }));

describe('usePipeline', () => {
  it('sends unified orchestrator flags for brain dump pipeline creation', async () => {
    const post = jest.fn().mockResolvedValue({ result: null });
    const get = jest.fn();
    const put = jest.fn();
    const request = jest.fn();
    const reset = jest.fn();
    const del = jest.fn();

    (useApi as jest.Mock).mockImplementation(() => ({
      data: null,
      loading: false,
      error: null,
      get,
      post,
      put,
      request,
      reset,
      delete: del,
    }));

    const { result } = renderHook(() => usePipeline());

    await act(async () => {
      await result.current.createFromBrainDump('Build autonomous QA workflows', 'qa');
    });

    expect(post).toHaveBeenCalledWith('/api/v1/canvas/pipeline/from-braindump', {
      text: 'Build autonomous QA workflows',
      context: 'qa',
      use_unified_orchestrator: true,
      skip_execution: true,
    });
  });
});
