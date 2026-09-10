jest.mock('next/navigation', () => ({ redirect: jest.fn() }));

import { redirect } from 'next/navigation';
import RootPage from '../page';

describe('RootPage', () => {
  beforeEach(() => {
    jest.mocked(redirect).mockClear();
  });

  it('redirects the root route to /landing/', () => {
    RootPage();
    expect(redirect).toHaveBeenCalledWith('/landing/');
  });
});
