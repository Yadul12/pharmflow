import React, { useEffect, useRef } from "react";
import Plotly from "plotly.js-dist-min";

interface PlotlyChartProps {
  data: Plotly.Data[];
  layout?: Partial<Plotly.Layout>;
  height?: number;
}

export const CHART_COLORS = {
  navy: "#0F243D",
  blue: "#1E56A0",
  steel: "#4E7EB3",
  teal: "#1D6F72",
  slate: "#64748B",
  amber: "#B45309",
  red: "#B42318",
  green: "#166534",
  lightBlue: "#93B5DB",
  grid: "#E8EDF3",
};

export const PlotlyChart: React.FC<PlotlyChartProps> = ({ data, layout = {}, height = 310 }) => {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const mergedLayout: Partial<Plotly.Layout> = {
      autosize: true,
      height,
      paper_bgcolor: "#FFFFFF",
      plot_bgcolor: "#FFFFFF",
      font: {
        family: "Inter, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif",
        size: 11.5,
        color: "#334155",
      },
      margin: { t: 22, r: 20, b: 44, l: 54 },
      hoverlabel: {
        bgcolor: "#0F243D",
        bordercolor: "#0F243D",
        font: { color: "#FFFFFF", size: 11.5, family: "Inter, sans-serif" },
      },
      legend: {
        orientation: "h",
        yanchor: "bottom",
        y: 1.02,
        xanchor: "left",
        x: 0,
        font: { size: 11 },
      },
      ...layout,
      xaxis: {
        gridcolor: CHART_COLORS.grid,
        linecolor: "#CBD5E1",
        zeroline: false,
        automargin: true,
        ...(layout.xaxis || {}),
      },
      yaxis: {
        gridcolor: CHART_COLORS.grid,
        linecolor: "#CBD5E1",
        zeroline: false,
        automargin: true,
        ...(layout.yaxis || {}),
      },
    };

    Plotly.react(el, data, mergedLayout, {
      responsive: true,
      displayModeBar: true,
      displaylogo: false,
      modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d", "toggleSpikelines"],
    });

    const handleResize = () => {
      if (containerRef.current) {
        Plotly.Plots.resize(containerRef.current);
      }
    };
    window.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
    };
  }, [data, layout, height]);

  useEffect(() => {
    const el = containerRef.current;
    return () => {
      if (el) Plotly.purge(el);
    };
  }, []);

  return <div ref={containerRef} style={{ width: "100%", minHeight: height }} />;
};
