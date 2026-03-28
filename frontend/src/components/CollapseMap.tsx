/**
 * CollapseMap — Cytoscape.js graph visualisation
 *
 * Colour coding:
 *   red     — NNM critical/high (no reroute)
 *   orange  — NNM medium (weak reroute)
 *   green   — NNM low/none (redundant)
 *   purple  — assumption node
 *   grey    — unscored
 */
import React, { useCallback, useMemo } from 'react'
import CytoscapeComponent from 'react-cytoscapejs'
import type { Core, NodeSingular } from 'cytoscape'
import { useStore } from '../store/useStore'
import type { CollapseRisk, NodeType } from '../api/client'

const RISK_COLOUR: Record<CollapseRisk | 'unscored', string> = {
  critical: '#ef4444',
  high:     '#f97316',
  medium:   '#eab308',
  low:      '#22c55e',
  none:     '#16a34a',
  unscored: '#6b7280',
}

const NODE_SHAPE: Partial<Record<NodeType, string>> = {
  person:          'ellipse',
  team:            'round-rectangle',
  vendor:          'diamond',
  contract_clause: 'hexagon',
  assumption:      'star',
  decision_gate:   'triangle',
  system:          'barrel',
  asset:           'round-tag',
}

export function CollapseMap() {
  const { graphData, analysis, selectedNodeId, stressLevel, selectNode } = useStore()

  const elements = useMemo(() => {
    if (!graphData) return []

    const scoreMap = analysis?.node_scores ?? {}

    const nodes = graphData.nodes.map(n => {
      const scores = scoreMap[n.id]
      const risk: CollapseRisk | 'unscored' = scores?.collapse_risk ?? 'unscored'
      const isAssumption = n.node_type === 'assumption'
      const colour = isAssumption ? '#a855f7' : RISK_COLOUR[risk]
      // Under stress, amplify colour towards red for high-load nodes
      const stressedLoad = Math.min(1, (n.attributes?.load ?? 0.5) + stressLevel * 0.4)
      const size = 24 + (scores?.nnm_score ?? 0) * 30 + stressedLoad * 10

      return {
        data: {
          id: n.id,
          label: n.label,
          colour,
          size,
          shape: NODE_SHAPE[n.node_type] ?? 'ellipse',
          nnm: scores?.nnm_score ?? 0,
          risk,
          selected: n.id === selectedNodeId,
        },
      }
    })

    const edges = graphData.edges.map(e => ({
      data: {
        id: e.id,
        source: e.source,
        target: e.target,
        label: e.edge_type.replace(/_/g, ' '),
        reliability: e.attributes?.reliability ?? 1,
        // Dim edges under stress if reliability is low
        opacity: Math.max(0.2, (e.attributes?.reliability ?? 1) - stressLevel * 0.3),
      },
    }))

    return [...nodes, ...edges]
  }, [graphData, analysis, selectedNodeId, stressLevel])

  const stylesheet = useMemo(() => [
    {
      selector: 'node',
      style: {
        'background-color': 'data(colour)',
        'width': 'data(size)',
        'height': 'data(size)',
        'shape': 'data(shape)',
        'label': 'data(label)',
        'color': '#e2e2e6',
        'font-size': '10px',
        'text-valign': 'bottom',
        'text-halign': 'center',
        'text-margin-y': '4px',
        'text-wrap': 'wrap',
        'text-max-width': '100px',
        'border-width': 0,
        'transition-property': 'background-color, width, height, border-width',
        'transition-duration': '300ms',
      },
    },
    {
      selector: 'node:selected',
      style: {
        'border-width': 3,
        'border-color': '#fff',
      },
    },
    {
      selector: 'edge',
      style: {
        'curve-style': 'bezier',
        'target-arrow-shape': 'triangle',
        'arrow-scale': 0.8,
        'line-color': '#374151',
        'target-arrow-color': '#374151',
        'opacity': 'data(opacity)',
        'width': 1.5,
      },
    },
  ], [])

  const layout = {
    name: 'cose',
    animate: true,
    animationDuration: 600,
    nodeRepulsion: 8000,
    idealEdgeLength: 90,
    gravity: 0.25,
  }

  const onCyInit = useCallback((cy: Core) => {
    cy.on('tap', 'node', (evt) => {
      const node = evt.target as NodeSingular
      selectNode(node.id())
    })
    cy.on('tap', (evt) => {
      if (evt.target === cy) selectNode(null)
    })
  }, [selectNode])

  if (!graphData) {
    return (
      <div style={styles.empty}>
        <p>Load a graph or run the demo to see the collapse map.</p>
      </div>
    )
  }

  return (
    <CytoscapeComponent
      elements={elements}
      stylesheet={stylesheet as any}
      layout={layout}
      cy={onCyInit}
      style={{ width: '100%', height: '100%', background: '#111113' }}
    />
  )
}

const styles = {
  empty: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    height: '100%',
    color: '#6b7280',
    fontSize: '14px',
  } as React.CSSProperties,
}
