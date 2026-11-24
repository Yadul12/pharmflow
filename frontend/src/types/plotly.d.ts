declare namespace Plotly {
  type Data = Record<string, unknown>;
  type Layout = Record<string, unknown>;
  type Config = Record<string, unknown>;
}

declare module "plotly.js-dist-min" {
  const Plotly: {
    react(
      root: HTMLElement,
      data: Plotly.Data[],
      layout?: Partial<Plotly.Layout>,
      config?: Partial<Plotly.Config>
    ): Promise<HTMLElement>;
    purge(root: HTMLElement): void;
    Plots: {
      resize(root: HTMLElement): void;
    };
  };
  export default Plotly;
}
